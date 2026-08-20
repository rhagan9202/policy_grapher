"""Chunks in the graph — the first layer that is derived rather than canonical.

Everything here is droppable and rebuildable. Chunk ids are keyed on a chunk's
place in the document's own section structure (chunking._chunk_id), so a rebuild
reproduces the same ids — and, more to the point, an edit or a chunker change
only moves the ids of the sections it actually touches. Anything anchored to a
chunk elsewhere survives. That property is what makes re-extraction safe.
"""

from neo4j import ManagedTransaction

from policy_grapher.chunking import Chunk

WRITE_CHUNKS = """
MATCH (v:DocumentVersion {version_id: $version_id})
UNWIND $chunks AS chunk
MERGE (c:Chunk {chunk_id: chunk.chunk_id})
SET c.text         = chunk.text,
    c.page         = chunk.page,
    c.section_path = chunk.section_path,
    c.ordinal      = chunk.ordinal
MERGE (v)-[:HAS_CHUNK]->(c)
RETURN count(DISTINCT c) AS written
"""

DROP_CHUNKS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk)
DETACH DELETE c
"""


class UnknownVersionError(Exception):
    """Raised when chunks are written against a version_id that names no
    :DocumentVersion.

    Without this, the leading `MATCH (v:DocumentVersion {version_id: ...})`
    silently matches nothing: `UNWIND` never executes, no chunk is written,
    and a caller trusting the return value walks away believing the write
    succeeded. `count(DISTINCT c)` is a global aggregate, so it always yields
    exactly one row — 0 only when no version matched, since a matched version
    always merges at least one chunk (write_chunks already short-circuits on
    an empty chunk list). That 0 is what triggers this.
    """


def write_chunks(tx: ManagedTransaction, *, version_id: str, chunks: list[Chunk]) -> int:
    """Attach chunks to a version. Returns how many distinct chunk nodes are
    now attached — taken from the query result, not from `len(chunks)`, so a
    duplicate chunk_id within one call or an unmatched version is reflected
    honestly rather than reported as if every chunk landed.

    This write is authoritative: an existing chunk_id has its text, page,
    section_path and ordinal overwritten (`SET`, not `ON CREATE SET`). A chunk
    id is a hash of where the chunk sits in the document's structure, not of its
    text, so re-ingesting an edited edition under the same version_id reaches
    existing ids carrying different text — and a store whose whole point is a
    verbatim quotation must not answer with the previous edition's words. It
    also means correctness here does not depend on the caller having dropped
    first; `ingest._write_document` still drops, to remove chunks the new run no
    longer produces at all, which no amount of overwriting can do.

    Raises UnknownVersionError if version_id names no :DocumentVersion.
    """
    if not chunks:
        return 0
    record = tx.run(
        WRITE_CHUNKS,
        {
            "version_id": version_id,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "page": c.page,
                    "section_path": c.section_path,
                    "ordinal": c.ordinal,
                }
                for c in chunks
            ],
        },
    ).single()
    written = record["written"]
    if written == 0:
        raise UnknownVersionError(
            f"no :DocumentVersion with version_id {version_id!r}; nothing was written"
        )
    return written


def drop_chunks(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove a version's chunks. The version and its document are untouched."""
    summary = tx.run(DROP_CHUNKS, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted
