"""What an embedding index remembers about itself.

Vectors from two different models are not comparable. Nothing about mixing them
raises: cosine similarity is perfectly happy to compare two points that came out
of different geometries, and it returns a number. The result is a retrieval layer
that keeps working, keeps answering, and is quietly wrong — for as long as nobody
re-checks, which for a similarity score is indefinitely.

So the index records whose vectors it holds, and a write under a different
identity is refused rather than accepted.
"""

INDEX_NAME = "chunk_embedding"


class EmbeddingModelMismatch(Exception):
    """An embedder was pointed at an index built by a different one."""


def check_identity(
    *,
    recorded_model: str,
    recorded_dimensions: int,
    model_id: str,
    dimensions: int,
) -> None:
    """Refuse a write whose geometry does not match what the index already holds.

    Both names appear in the message on purpose: the person reading it needs to
    know which of the two is the one they did not mean to configure.
    """
    if recorded_model != model_id:
        raise EmbeddingModelMismatch(
            f"index {INDEX_NAME!r} holds vectors from {recorded_model!r}, but the "
            f"configured embedder is {model_id!r}. Vectors from two models are not "
            f"comparable — mixing them returns wrong neighbours without erroring. "
            f"Re-embed the corpus under one model, or configure the other one back."
        )
    if recorded_dimensions != dimensions:
        raise EmbeddingModelMismatch(
            f"index {INDEX_NAME!r} holds {recorded_dimensions}-dimension vectors "
            f"from {recorded_model!r}, but the configured embedder produces "
            f"{dimensions}. Same name, different geometry: the index cannot hold "
            f"both."
        )
