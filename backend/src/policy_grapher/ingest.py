"""Merge a parsed corpus into Neo4j. Additive: MERGE creates and updates, never deletes."""

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from neo4j import Driver, ManagedTransaction

from policy_grapher.builds import clear_build
from policy_grapher.changes.diff import drop_changes
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import drop_chunks, write_chunks
from policy_grapher.documents import allocate_slugs, reconcile_slugs
from policy_grapher.merges import apply_merges
from policy_grapher.models import DocumentIngestResult, DocumentRef, IngestResult
from policy_grapher.obligations import drop_obligations
from policy_grapher.pipeline import pipeline_stamp
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
from policy_grapher.versions import (
    edition_is_current,
    link_supersession,
    merge_version,
)

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
        # ADR-032. A manifest naming both spellings of one document recreates the
        # node a person merged away, so recorded merges are re-applied here rather
        # than being silently undone — the failure `:LinkDecision` exists to
        # prevent for links, in a second place. A no-op when nothing is recorded.
        session.execute_write(apply_merges)

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
        # Derived from the one fact rather than tracked beside it, so the two
        # cannot disagree about what happened.
        outcome="unchanged" if merged.chunks_written is None else "written",
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


# What the parser learned about this document's own references section, written
# down because nothing can recompute it later.
#
# `locate_references` returns an unknown format rather than raising when it
# cannot find the section (sources/pdf.py), so `references=()` means one of two
# different things: the document cites nothing, or nobody could read what it
# cites. Until now that distinction survived only in the `DocumentIngestResult`
# the write returned — a reader who reloaded the page lost it, and a node with
# no outgoing edges rendered the same either way. ADR-015 calls that shape the
# most dangerous output this tool can produce, and it is the same shape here.
#
# Three states, and the absent one is deliberate: a `:Document` created by a
# manifest row or by being cited elsewhere has never been through the parser, so
# it carries neither property. `false` means parsed and no section found. A
# reader must not collapse absent into `false` — "we have not looked" and "we
# looked and there was nothing" are the two the distinction exists to separate.
#
# Both properties accumulate rather than overwrite, because reference state is a
# fact about the document and `MERGE_EDGES` below already treats it that way: no
# ingest path deletes a `:REFERENCES` edge (ADR-007), so a document's edges are
# the union of every parse of it. A status that described only the newest parse
# would contradict the edges standing beside it — re-ingest an edition whose
# references section has become unreadable and the graph would show the earlier
# parse's dependencies next to a flag saying nothing was read.
#
# Accumulation resolves that in the one direction ADR-015 allows. `section_found`
# is sticky-true: once any parse has read this document's references, the edges
# from that parse persist, so the document has a readable references section and
# a later failure to find one must not claim otherwise. Unattributed entries
# union: a later parse that reads cleanly must not silently retire the gaps an
# earlier parse reported while that parse's edges remain, which would be exactly
# the false all-clear. Over-reporting a gap is a person's to close; under-
# reporting one is the output ADR-015 names as most dangerous. Re-ingesting the
# same bytes reports the same entries, so the write stays idempotent (ADR-042).
MERGE_DOCUMENT = """
MERGE (d:Document {slug: $slug})
SET d.name = $name,
    d.references_section_found =
        coalesce(d.references_section_found, false) OR $section_found,
    d.references_unattributed =
        [entry IN coalesce(d.references_unattributed, [])
         WHERE NOT entry IN $unattributed] + $unattributed
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
    section_found: bool,
    unattributed: list[str],
) -> tuple[int, int, str, int | None]:
    nodes_created = (
        tx.run(
            MERGE_DOCUMENT,
            {
                "slug": slug,
                "name": name,
                "section_found": section_found,
                # Stored as the names themselves rather than a count. A reader
                # deciding whether to trust a neighbourhood needs to know *which*
                # citations went unresolved — a bare number says something is
                # missing without saying enough to act on it.
                "unattributed": unattributed,
            },
        )
        .consume()
        .counters.nodes_created
    )
    if cited:
        nodes_created += (
            tx.run(MERGE_CITED, {"docs": cited}).consume().counters.nodes_created
        )
    relationships_created = 0
    if edges:
        relationships_created = (
            tx.run(MERGE_EDGES, {"edges": edges})
            .consume()
            .counters.relationships_created
        )

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
    #
    # The derived layer goes first, in the order `links/rebuild.py` established
    # for the same hazard: changes, then obligations, then chunks. `drop_chunks`
    # is a DETACH DELETE, so dropping chunks alone destroys the `:ANCHORED_IN`
    # edges obligations cite passages through, while the obligations themselves
    # survive on `:MANDATES` — unanchored, and unreadable by every path that
    # needs a citation. Found on 2026-09-08 against a real rebuilt graph, where
    # the screen read "62 obligations. Showing the first 0."
    #
    # Dropping rather than re-anchoring is the honest answer, not the cheap one:
    # the text has been re-chunked, so an extraction taken from the old chunks
    # no longer describes what the edition now holds. The edition returns to
    # never-built and is rebuilt from the text that is actually there.
    #
    # None of that is worth doing when it would reproduce what is already there.
    # Re-adding a file is routine — ADR-007 makes ingest additive so that it is
    # safe — and the map makes adding a document the most prominent action in
    # the product, so the likeliest re-ingest is somebody adding the same file
    # twice. Answering that with an hour of extraction and the loss of every
    # human verdict resting on it is the behaviour ADR-042 narrows: when the
    # source bytes and the pipeline that chunks them both match what the edition
    # already carries, nothing here runs.
    #
    # The skip covers this block and nothing above it. The document write, its
    # reference edges and the record of what its references section yielded have
    # already happened, and they refresh on every ingest — otherwise a document
    # whose references could not be read once would be frozen in that state, and
    # the map would keep asserting an unknown that had since become knowable.
    #
    # The bytes half of that condition is already settled: `merge_version` above
    # would have raised rather than return, had this file disagreed with the
    # checksum the edition carries. What is left to ask is whether the pipeline
    # still produces what is stored.
    stamp = pipeline_stamp()
    chunks = chunk_pages(pages, version_id=version)
    # Refused before the skip is decided, not after it. A source that yields no
    # text is a failed read whichever path follows, and answering it with
    # "already present, nothing to do" would report that failure as a healthy
    # outcome — the same false all-clear ADR-015 exists to prevent, arriving
    # through the door this skip opened. The extraction has already happened by
    # the time control reaches here, so the check costs nothing the ingest was
    # not paying anyway. Previously this was `written == 0` after the write,
    # which is the same condition: `write_chunks` returns 0 only for an empty
    # chunk list, and raises rather than returning 0 for anything else.
    if not chunks:
        raise DocumentSourceError(
            f"{filename!r} produced no text to chunk — a scanned PDF with no text layer, "
            "or an extraction failure. Nothing was written; the previous chunks are unchanged."
        )

    if edition_is_current(tx, version_id=version, pipeline_stamp=stamp):
        # None rather than 0: no chunks were written, which is a different fact
        # from a write that produced none.
        written = None
    else:
        drop_changes(tx, version_id=version)
        drop_obligations(tx, version_id=version)
        clear_build(tx, version_id=version)
        drop_chunks(tx, version_id=version)
        written = write_chunks(
            tx, version_id=version, chunks=chunks, pipeline_stamp=stamp
        )

    # Below the branch, because it belongs to the document write above it rather
    # than to the chunk rewrite: a parse that newly reads a references section
    # creates the documents it names on either path, and a document nothing
    # describes is an external reference.
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
    # None when the edition's chunks were already current and were left
    # standing, which is not the same fact as a write that produced none.
    chunks_written: int | None


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
        nodes_created, relationships_created, version_id, chunks_written = (
            session.execute_write(
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
                section_found=extracted.report.section_found,
                unattributed=list(extracted.report.unattributed),
            )
        )
    return IngestedDocument(
        slug=slug,
        nodes_created=nodes_created,
        relationships_created=relationships_created,
        version_id=version_id,
        chunks_written=chunks_written,
    )
