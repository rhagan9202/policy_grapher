"""Replace the whole derived layer for one edition, keeping every human decision.

The derived layer — chunks, obligations, proposals, and the `IMPLEMENTS` edges
replay writes — is dropped and rebuilt here. `:LinkDecision` is canonical and is
never read for deletion by anything in this module: it is what the rebuild
*replays*, and the reason a re-extraction is safe to run at all.

Two shape decisions worth knowing about:

**Extraction happens outside the transaction.** The plan called for one
transaction end to end, and the atomic swap it was protecting is preserved — but
extraction calls a model over HTTP once per chunk, and holding a Neo4j write
transaction open across minutes of network I/O holds locks for the duration and
invites a transaction timeout. So the expensive, side-effect-free work (read the
PDF, chunk it, extract) runs first, and everything that mutates the graph runs
afterwards inside a single `execute_write`. A failure anywhere in the write still
rolls the whole thing back.

**Re-chunking reads the original PDF, not the stored chunks.** Reassembling pages
from chunk text is lossy — overlap is duplicated, page boundaries are gone — and,
more to the point, it could never produce a *different* chunking, which is the
main reason to rebuild in the first place. So a version's `source_uri` has to
still resolve to a readable file. When it does not, this fails loudly rather than
dropping a version's entire text and reporting success.
"""

from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from neo4j import Driver, ManagedTransaction, RoutingControl

from policy_grapher.changes.diff import drop_changes
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import drop_chunks, write_chunks
from policy_grapher.links.decisions import replay_decisions
from policy_grapher.links.propose import propose_links
from policy_grapher.obligations import drop_obligations, write_obligations
from policy_grapher.sources import pdf

READ_SOURCE = """
MATCH (v:DocumentVersion {version_id: $version_id})
RETURN v.source_uri AS source_uri
"""


class MissingSourceError(Exception):
    """The edition, or the file it was read from, is not there to rebuild from."""


def _source_path(driver: Driver, database: str, version_id: str) -> Path:
    records, _, _ = driver.execute_query(
        READ_SOURCE,
        {"version_id": version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if not records:
        raise MissingSourceError(f"no :DocumentVersion with version_id {version_id!r}")

    source_uri = records[0]["source_uri"]
    path = Path(unquote(urlparse(source_uri).path))
    if not path.is_file():
        raise MissingSourceError(
            f"{version_id!r} was read from {source_uri!r}, which is not a readable "
            f"file now. Re-chunking needs the original document; nothing was dropped."
        )
    return path


def _write_rebuild(
    tx: ManagedTransaction,
    *,
    version_id: str,
    chunks: list,
    extracted: list[tuple[str, list[str], list]],
    candidate_version_ids: list[str],
    proposer: str,
) -> dict[str, int]:
    # Obligations first: DETACH DELETE takes their IMPLEMENTS and
    # IMPLEMENTS_PROPOSED edges with them, so the derived link layer is cleared
    # by the same statement rather than needing one of its own. Chunks follow,
    # since an obligation anchors to one.
    # Changes first: a :Change AFFECTS an obligation, so dropping obligations
    # underneath it would leave a change a reviewer can see and cannot trace.
    # The diff is cheap to re-run and is not re-run here — a rebuild changes what
    # the editions say, and which pair to re-diff is the caller's decision.
    changes_dropped = drop_changes(tx, version_id=version_id)
    obligations_dropped = drop_obligations(tx, version_id=version_id)
    chunks_dropped = drop_chunks(tx, version_id=version_id)

    chunks_written = write_chunks(tx, version_id=version_id, chunks=chunks)
    obligations_written = 0
    for chunk_id, section_path, obligations in extracted:
        obligations_written += write_obligations(
            tx,
            version_id=version_id,
            chunk_id=chunk_id,
            section_path=section_path,
            obligations=obligations,
        )

    proposed = 0
    if candidate_version_ids:
        proposed = propose_links(
            tx,
            org_version_id=version_id,
            candidate_version_ids=candidate_version_ids,
            proposer=proposer,
        )

    replayed = replay_decisions(tx)
    return {
        "changes_dropped": changes_dropped,
        "chunks_dropped": chunks_dropped,
        "obligations_dropped": obligations_dropped,
        "chunks_written": chunks_written,
        "obligations_written": obligations_written,
        "proposed": proposed,
        **replayed,
    }


def rebuild_derived(
    driver: Driver,
    database: str,
    *,
    version_id: str,
    extractor,
    candidate_version_ids: list[str] | None = None,
    proposer: str = "lexical-v1",
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Rebuild one edition's derived layer and replay every recorded decision.

    Returns what happened, including `unpromotable` — approvals the replay could
    not apply because re-extraction no longer produces one side. A caller that
    reads only the happy counts would see a healthy-looking rebuild in exactly the
    case where a human decision has stopped being represented in the graph.

    Raises MissingSourceError before touching the graph if the edition or its
    source document is not there.
    """
    path = _source_path(driver, database, version_id)
    document = pdf.extract_document(path)
    chunks = chunk_pages(document.pages, version_id=version_id)

    # Outside the transaction on purpose — see the module docstring. A loop
    # rather than a comprehension so progress can be reported per chunk: with a
    # real model this is one call each over dozens of chunks, and a caller
    # watching a blank response for minutes cannot tell work from a hang.
    total = len(chunks)
    extracted: list[tuple[str, list[str], list]] = []
    for done, chunk in enumerate(chunks, start=1):
        found = extractor.extract(chunk.text, section_path=chunk.section_path)
        if found:
            extracted.append((chunk.chunk_id, chunk.section_path, found))
        if on_progress is not None:
            on_progress(done, total)

    with driver.session(database=database) as session:
        return session.execute_write(
            _write_rebuild,
            version_id=version_id,
            chunks=chunks,
            extracted=extracted,
            candidate_version_ids=list(candidate_version_ids or []),
            proposer=proposer,
        )
