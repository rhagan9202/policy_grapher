"""Merge a parsed corpus into Neo4j. Additive: MERGE creates and updates, never deletes."""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from neo4j import Driver, ManagedTransaction

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import drop_chunks, write_chunks
from policy_grapher.documents import allocate_slugs, reconcile_slugs
from policy_grapher.models import DocumentIngestResult, DocumentRef, IngestResult
from policy_grapher.sources import is_document_source, pdf, resolve_source_path
from policy_grapher.sources.document import DocumentSourceError, ExtractedDocument
from policy_grapher.sources.manifest import ParsedCorpus, parse_corpus
from policy_grapher.sources.provenance import (
    DESCRIBES,
    DOCUMENT,
    MANIFEST,
    MERGE_SOURCE,
    REFRESH_EXTERNAL,
    source_id,
)
from policy_grapher.versions import link_supersession, merge_version

MERGE_CORPUS = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name
"""

MERGE_EXTERNAL = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name
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
    filename: str,
    external_docs: list[dict],
    corpus_docs: list[dict],
    edges: list[dict],
) -> tuple[int, int]:
    nodes_created = 0
    relationships_created = 0

    # The :External label is not set here — it is refreshed at the end, from
    # provenance (see provenance.REFRESH_EXTERNAL).
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

    # Provenance bookkeeping: consumed for its side effects, but not counted
    # toward nodes_created/relationships_created — those report Document nodes
    # and REFERENCES edges, which is what the caller asked about.
    tx.run(
        MERGE_SOURCE,
        {"id": source_id(MANIFEST, filename), "kind": MANIFEST, "filename": filename},
    ).consume()
    tx.run(
        DESCRIBES,
        {"id": source_id(MANIFEST, filename), "slugs": [d["slug"] for d in corpus_docs]},
    ).consume()
    tx.run(
        REFRESH_EXTERNAL,
        {"slugs": [d["slug"] for d in corpus_docs + external_docs]},
    ).consume()

    return nodes_created, relationships_created


def ingest_parsed(
    driver: Driver, database: str, parsed: ParsedCorpus, filename: str
) -> IngestResult:
    # Slugs are resolved before the write transaction opens (`reconcile_slugs`
    # reads via `driver.execute_query`, which cannot run inside a
    # `session.execute_write` callback). Names already stored — by an earlier
    # manifest or by a PDF ingested first — keep the slug they hold; only new
    # names are assigned over the name set. See `documents.reconcile_slugs`.
    slugs = reconcile_slugs(driver, database, parsed.all_names)

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
            filename=filename,
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
) -> IngestResult | DocumentIngestResult:
    path = resolve_source_path(filename, data_dir)
    if not is_document_source(path):
        return ingest_parsed(driver, database, parse_corpus(path), path.name)

    extracted = pdf.extract_document(path)
    merged = ingest_document(driver, database, extracted, path)
    return DocumentIngestResult(
        format=extracted.report.format,
        document=DocumentRef(slug=merged.slug, name=extracted.name),
        nodes_created=merged.nodes_created,
        relationships_created=merged.relationships_created,
        references_attributed=len(extracted.report.attributed),
        references_unattributed=list(extracted.report.unattributed),
        self_references_skipped=extracted.self_references_skipped,
        version_id=merged.version_id,
        chunks_written=merged.chunks_written,
    )


MERGE_DOCUMENT = """
MERGE (d:Document {slug: $slug})
SET d.name = $name
"""

MERGE_CITED = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
ON CREATE SET d.name = doc.name
"""


def _write_document(
    tx: ManagedTransaction,
    *,
    filename: str,
    slug: str,
    name: str,
    cited: list[dict],
    edges: list[dict],
    path: Path,
    checksum: str,
    effective_date: date | None,
    pages: list[str],
) -> tuple[int, int, str, int]:
    nodes_created = tx.run(MERGE_DOCUMENT, {"slug": slug, "name": name}).consume().counters.nodes_created
    if cited:
        nodes_created += tx.run(MERGE_CITED, {"docs": cited}).consume().counters.nodes_created
    relationships_created = 0
    if edges:
        relationships_created = tx.run(
            MERGE_EDGES, {"edges": edges}
        ).consume().counters.relationships_created

    # Provenance bookkeeping: consumed for its side effects, but not counted
    # toward nodes_created/relationships_created — those report Document nodes
    # and REFERENCES edges, which is what the caller asked about. Only the
    # document's own subject is described; what it cites is not (that stays
    # external until some ingest describes it first-hand).
    tx.run(
        MERGE_SOURCE,
        {"id": source_id(DOCUMENT, filename), "kind": DOCUMENT, "filename": filename},
    ).consume()
    tx.run(
        DESCRIBES,
        {"id": source_id(DOCUMENT, filename), "slugs": [slug]},
    ).consume()

    version = merge_version(
        tx,
        document_slug=slug,
        effective_date=effective_date,
        checksum=checksum,
        source_uri=f"file://{path}",
    )
    link_supersession(tx, slug)

    # Drop before write, inside this same transaction: a re-ingest (a chunker
    # improvement, or the same file scanned again) must *replace* this
    # version's chunks, not leave the previous run's chunks orphaned beside
    # the new ones. `merge_version` already resolved `version` above — bound,
    # not recomputed, since it is the same resolution `chunk_pages` and
    # `write_chunks` need to attach against.
    drop_chunks(tx, version_id=version)
    written = write_chunks(
        tx,
        version_id=version,
        chunks=chunk_pages(pages, version_id=version),
    )
    # Because the drop runs first, a document that yields no text does not merely
    # store nothing — it *deletes* whatever a previous ingest stored, and returns
    # 200 with a healthy-looking node count. A scanned PDF with no text layer, a
    # pypdf regression, or a caller that forgets to pass `pages` all reach here.
    # Failing rolls the whole transaction back, so the previous chunk set
    # survives. This is the document path only: a manifest legitimately produces
    # no chunks and never runs this function.
    if written == 0:
        raise DocumentSourceError(
            f"{filename!r} produced no text to chunk — a scanned PDF with no text layer, "
            "or an extraction failure. Nothing was written; the previous chunks are unchanged."
        )

    tx.run(
        REFRESH_EXTERNAL,
        {"slugs": [slug, *(entry["slug"] for entry in cited)]},
    ).consume()

    return nodes_created, relationships_created, version, written


@dataclass(frozen=True)
class IngestedDocument:
    """What merging one document into the graph produced.

    A plain tuple return let `nodes_created` and `relationships_created` — two
    adjacent, same-typed ints — swap silently past every type checker, and let
    a caller unpack it with a tolerant `*_` that would absorb a future field
    change unnoticed. Named fields make both a caller error the type checker
    catches, the same discipline `ExtractedDocument`/`ExtractionReport` in
    `sources.document` already apply to what a PDF extraction produces.

    `version_id` and `chunks_written` matter most on a re-ingest: a second
    edition of an already-known document creates no `:Document` node, so
    `nodes_created` alone reads as "nothing happened" while the edition's text
    lands regardless (STORY-066).
    """

    slug: str
    nodes_created: int
    relationships_created: int
    version_id: str
    chunks_written: int


def ingest_document(
    driver: Driver, database: str, extracted: ExtractedDocument, path: Path
) -> IngestedDocument:
    """Merge one extracted document and the documents it cites.

    Slugs are resolved for the whole batch (this document plus every name it
    cites) *before* the write transaction opens: `allocate_slugs` reads via
    `driver.execute_query`, which cannot run inside a `session.execute_write`
    callback, and two names in this same batch can contest the same base slug
    before either exists in the database — see `documents.allocate_slugs` for
    why resolving them one at a time (with plain `allocate_slug`) silently
    collapses distinct documents into one node.

    The checksum is computed here too, alongside slug resolution, for the same
    reason: it is a read (of the file), not a write, and belongs outside the
    transaction with the rest of this function's reads.
    """
    slugs = allocate_slugs(driver, database, [extracted.name, *extracted.references])
    slug = slugs[extracted.name]
    cited = [{"slug": slugs[name], "name": name} for name in extracted.references]
    edges = [{"source": slug, "target": entry["slug"]} for entry in cited]
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    with driver.session(database=database) as session:
        nodes_created, relationships_created, version_id, chunks_written = session.execute_write(
            _write_document,
            filename=path.name,
            slug=slug,
            name=extracted.name,
            cited=cited,
            edges=edges,
            path=path,
            checksum=checksum,
            effective_date=extracted.effective_date,
            pages=extracted.pages,
        )
    return IngestedDocument(
        slug=slug,
        nodes_created=nodes_created,
        relationships_created=relationships_created,
        version_id=version_id,
        chunks_written=chunks_written,
    )
