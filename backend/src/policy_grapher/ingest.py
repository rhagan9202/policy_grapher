"""Merge a parsed corpus into Neo4j. Additive: MERGE creates and updates, never deletes."""

from pathlib import Path

from neo4j import Driver, ManagedTransaction

from policy_grapher.documents import allocate_slugs
from policy_grapher.models import IngestResult
from policy_grapher.slugs import assign_slugs
from policy_grapher.sources.document import ExtractedDocument
from policy_grapher.sources.manifest import ParsedCorpus, parse_corpus, resolve_csv_path

MERGE_CORPUS = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name
REMOVE d:External
"""

MERGE_EXTERNAL = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name, d:External
"""

MERGE_EDGES = """
UNWIND $edges AS edge
MATCH (source:Document {slug: edge.source})
MATCH (target:Document {slug: edge.target})
MERGE (source)-[:REFERENCES]->(target)
"""


def _write_ingest(
    tx: ManagedTransaction,
    *,
    external_docs: list[dict],
    corpus_docs: list[dict],
    edges: list[dict],
) -> tuple[int, int]:
    nodes_created = 0
    relationships_created = 0

    # External first, then corpus, so a node can transition either direction across
    # ingests: the corpus pass strips :External from a node first seen as a citation
    # target, and the external pass adds it to a node that was a corpus row in an
    # earlier ingest but is now only cited.
    for statement, payload in (
        (MERGE_EXTERNAL, external_docs),
        (MERGE_CORPUS, corpus_docs),
    ):
        if not payload:
            continue
        summary = tx.run(statement, {"docs": payload}).consume()
        nodes_created += summary.counters.nodes_created

    if edges:
        summary = tx.run(MERGE_EDGES, {"edges": edges}).consume()
        relationships_created += summary.counters.relationships_created

    return nodes_created, relationships_created


def ingest_parsed(
    driver: Driver, database: str, parsed: ParsedCorpus
) -> IngestResult:
    slugs = assign_slugs(parsed.all_names)

    corpus_docs = [
        {"slug": slugs[name], "name": name}
        for name in sorted(parsed.corpus_names)
    ]
    external_docs = [
        {"slug": slugs[name], "name": name}
        for name in sorted(parsed.external_names)
    ]
    edges = [
        {"source": slugs[source], "target": slugs[target]}
        for source, target in parsed.edges
    ]

    # All three statements run inside one explicit write transaction, so a failure
    # partway through (e.g. the edge statement after the node statements) rolls
    # back everything instead of leaving a nodes-but-no-edges graph committed.
    with driver.session(database=database) as session:
        nodes_created, relationships_created = session.execute_write(
            _write_ingest,
            external_docs=external_docs,
            corpus_docs=corpus_docs,
            edges=edges,
        )

    return IngestResult(
        nodes_created=nodes_created,
        relationships_created=relationships_created,
        self_references_skipped=parsed.self_references_skipped,
        suspected_duplicates=[list(group) for group in parsed.suspected_duplicates],
    )


def ingest_file(
    driver: Driver, database: str, filename: str, data_dir: Path
) -> IngestResult:
    path = resolve_csv_path(filename, data_dir)
    return ingest_parsed(driver, database, parse_corpus(path))


MERGE_DOCUMENT = """
MERGE (d:Document {slug: $slug})
SET d.name = $name
REMOVE d:External
"""

MERGE_CITED = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
ON CREATE SET d.name = doc.name, d:External
"""


def _write_document(
    tx: ManagedTransaction, *, slug: str, name: str, cited: list[dict], edges: list[dict]
) -> tuple[int, int]:
    nodes_created = tx.run(MERGE_DOCUMENT, {"slug": slug, "name": name}).consume().counters.nodes_created
    if cited:
        nodes_created += tx.run(MERGE_CITED, {"docs": cited}).consume().counters.nodes_created
    relationships_created = 0
    if edges:
        relationships_created = tx.run(
            MERGE_EDGES, {"edges": edges}
        ).consume().counters.relationships_created
    return nodes_created, relationships_created


def ingest_document(
    driver: Driver, database: str, extracted: ExtractedDocument
) -> tuple[str, int, int]:
    """Merge one extracted document and the documents it cites.

    Slugs are resolved for the whole batch (this document plus every name it
    cites) *before* the write transaction opens: `allocate_slugs` reads via
    `driver.execute_query`, which cannot run inside a `session.execute_write`
    callback, and two names in this same batch can contest the same base slug
    before either exists in the database — see `documents.allocate_slugs` for
    why resolving them one at a time (with plain `allocate_slug`) silently
    collapses distinct documents into one node.
    """
    slugs = allocate_slugs(driver, database, [extracted.name, *extracted.references])
    slug = slugs[extracted.name]
    cited = [{"slug": slugs[name], "name": name} for name in extracted.references]
    edges = [{"source": slug, "target": entry["slug"]} for entry in cited]

    with driver.session(database=database) as session:
        nodes_created, relationships_created = session.execute_write(
            _write_document, slug=slug, name=extracted.name, cited=cited, edges=edges
        )
    return slug, nodes_created, relationships_created
