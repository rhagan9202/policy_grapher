"""Chunks in the graph — the first layer that is derived rather than canonical.

Everything here is droppable and rebuildable. Chunk ids are deterministic
(chunking.Chunk), so a rebuild reproduces the same ids and anything anchored to
a chunk survives it. That property is what makes re-extraction safe.
"""

from neo4j import ManagedTransaction

from policy_grapher.chunking import Chunk

WRITE_CHUNKS = """
MATCH (v:DocumentVersion {version_id: $version_id})
UNWIND $chunks AS chunk
MERGE (c:Chunk {chunk_id: chunk.chunk_id})
ON CREATE SET c.text         = chunk.text,
              c.page         = chunk.page,
              c.section_path = chunk.section_path,
              c.ordinal      = chunk.ordinal
MERGE (v)-[:HAS_CHUNK]->(c)
"""

DROP_CHUNKS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk)
DETACH DELETE c
"""


def write_chunks(tx: ManagedTransaction, *, version_id: str, chunks: list[Chunk]) -> int:
    """Attach chunks to a version. Returns how many are now attached."""
    if not chunks:
        return 0
    tx.run(
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
    ).consume()
    return len(chunks)


def drop_chunks(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove a version's chunks. The version and its document are untouched."""
    summary = tx.run(DROP_CHUNKS, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted
