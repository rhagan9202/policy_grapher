"""Embedding, behind a provider-agnostic port — and an index that remembers.

The port mirrors `extraction`: a protocol, a null default that needs no model,
and a factory that fails on an unknown name at startup rather than mid-run. What
is different here is `ensure_vector_index`, which exists because of the failure
described in `schema.py`: a swapped embedder does not error, it degrades silently.
"""

from typing import TYPE_CHECKING, Protocol

from neo4j import Driver, RoutingControl

from policy_grapher.embedding.schema import (
    INDEX_NAME,
    EmbeddingModelMismatch,
    check_identity,
)

if TYPE_CHECKING:
    from policy_grapher.config import Settings

__all__ = [
    "Embedder",
    "EmbeddingModelMismatch",
    "build_embedder",
    "embed_chunks",
    "ensure_vector_index",
]


class Embedder(Protocol):
    """The contract every adapter meets.

    `model_id` is recorded on the index, so it must change whenever the thing
    behind it changes — model, revision, or provider.
    """

    model_id: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


READ_INDEX = """
MATCH (i:EmbeddingIndex {name: $name})
RETURN i.model_id AS model_id, i.dimensions AS dimensions
"""

RECORD_INDEX = """
MERGE (i:EmbeddingIndex {name: $name})
SET i.model_id = $model_id, i.dimensions = $dimensions
"""

UNEMBEDDED_CHUNKS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk)
WHERE c.embedding IS NULL OR c.embedding_model <> $model_id
RETURN c.chunk_id AS chunk_id, c.text AS text
ORDER BY c.ordinal
"""

WRITE_EMBEDDINGS = """
UNWIND $rows AS row
MATCH (c:Chunk {chunk_id: row.chunk_id})
SET c.embedding = row.embedding,
    c.embedding_model = $model_id
"""


def build_embedder(settings: Settings) -> Embedder:
    """Resolve the configured adapter. Unknown names fail at startup, not mid-run."""
    from policy_grapher.embedding.local import LocalEmbedder
    from policy_grapher.embedding.null import NullEmbedder

    if settings.embedder_adapter == "null":
        return NullEmbedder()
    if settings.embedder_adapter == "local":
        return LocalEmbedder(model=settings.embedder_model)
    raise ValueError(f"unknown embedder adapter: {settings.embedder_adapter!r}")


def ensure_vector_index(driver: Driver, database: str, *, embedder: Embedder) -> None:
    """Create the vector index if absent, and refuse a mismatched embedder.

    The refusal is the point. Creating an index is trivial; noticing that the
    corpus already holds someone else's vectors is the thing no similarity score
    will ever tell you.
    """
    if embedder.dimensions == 0:
        return

    records, _, _ = driver.execute_query(
        READ_INDEX,
        {"name": INDEX_NAME},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if records:
        check_identity(
            recorded_model=records[0]["model_id"],
            recorded_dimensions=records[0]["dimensions"],
            model_id=embedder.model_id,
            dimensions=embedder.dimensions,
        )
        return

    # The index name and dimensions are not parameterisable in Cypher DDL, so
    # they are interpolated. Both come from configuration this process resolved,
    # never from a request; INDEX_NAME is a module constant and `dimensions` is
    # an int the check below enforces.
    dimensions = int(embedder.dimensions)
    driver.execute_query(
        f"CREATE VECTOR INDEX {INDEX_NAME} IF NOT EXISTS "
        "FOR (c:Chunk) ON c.embedding "
        "OPTIONS {indexConfig: {"
        f"`vector.dimensions`: {dimensions}, "
        "`vector.similarity_function`: 'cosine'}}",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    driver.execute_query(
        RECORD_INDEX,
        {
            "name": INDEX_NAME,
            "model_id": embedder.model_id,
            "dimensions": dimensions,
        },
        database_=database,
        routing_=RoutingControl.WRITE,
    )


def embed_chunks(
    driver: Driver, database: str, *, version_id: str, embedder: Embedder
) -> int:
    """Embed an edition's chunks. Returns how many vectors were newly written.

    Idempotent: a chunk already carrying a vector from this same model is skipped,
    so re-running returns 0 rather than rewriting the corpus. A chunk with no text
    is skipped too — an empty string embeds to a real point that means nothing and
    would sit in the index as a plausible neighbour for anything.

    Raises EmbeddingModelMismatch before writing anything if the index already
    holds another model's vectors.
    """
    if embedder.dimensions == 0:
        return 0

    ensure_vector_index(driver, database, embedder=embedder)

    records, _, _ = driver.execute_query(
        UNEMBEDDED_CHUNKS,
        {"version_id": version_id, "model_id": embedder.model_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    pending = [r for r in records if r["text"] and r["text"].strip()]
    if not pending:
        return 0

    vectors = embedder.embed([r["text"] for r in pending])
    rows = [
        {"chunk_id": record["chunk_id"], "embedding": vector}
        for record, vector in zip(pending, vectors, strict=True)
    ]
    driver.execute_query(
        WRITE_EMBEDDINGS,
        {"rows": rows, "model_id": embedder.model_id},
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    return len(rows)
