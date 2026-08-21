"""The embedding port, and the guard on the failure that does not look like one."""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.config import Settings
from policy_grapher.embedding import build_embedder, embed_chunks, ensure_vector_index
from policy_grapher.embedding.null import NullEmbedder
from policy_grapher.embedding.schema import EmbeddingModelMismatch


class FakeEmbedder:
    """A stand-in with a declared identity and no model behind it.

    The guard tests below are about what the graph records and refuses, not about
    embedding quality — a real model would make them slow and would not make them
    stronger.
    """

    def __init__(self, *, model_id: str = "fake-a", dimensions: int = 4) -> None:
        self.model_id = model_id
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [float((hash(text) >> (8 * i)) % 100) / 100.0 for i in range(self.dimensions)]
            for text in texts
        ]


def _local_or_skip():
    from policy_grapher.embedding.local import LocalEmbedder

    embedder = LocalEmbedder(model="sentence-transformers/all-MiniLM-L6-v2")
    try:
        embedder.embed(["warm up"])
    except Exception as exc:  # noqa: BLE001 - any load failure means the same thing
        pytest.skip(
            "THE LOCAL EMBEDDER WAS NOT EXERCISED: the model could not be loaded "
            f"({type(exc).__name__}: {exc}). A green suite does not mean it works."
        )
    return embedder


# --- the port -----------------------------------------------------------------


def test_the_default_embedder_needs_no_model():
    """The suite has to run on a machine with no model downloaded."""
    assert build_embedder(Settings(_env_file=None)).model_id == "null"


def test_the_null_embedder_produces_no_vectors():
    """Not zero vectors: a zero vector is a real point in the space and would be
    returned as everything's nearest neighbour."""
    assert NullEmbedder().embed(["The Director shall notify."]) == []
    assert NullEmbedder().dimensions == 0


def test_an_unknown_embedder_name_fails_loudly():
    with pytest.raises(ValueError, match="unknown embedder"):
        build_embedder(Settings(_env_file=None, embedder_adapter="magic"))


def test_the_local_embedder_returns_vectors_of_its_declared_width():
    embedder = _local_or_skip()
    vectors = embedder.embed(["The Director shall notify.", "Another clause."])

    assert len(vectors) == 2
    assert all(len(v) == embedder.dimensions for v in vectors)


def test_the_local_embedder_is_deterministic():
    """A rebuild re-embeds. If the vector moved, every stored neighbour moved
    with it for no reason anybody could see."""
    embedder = _local_or_skip()
    text = "The Director shall notify the Comptroller within 24 hours."

    assert embedder.embed([text]) == embedder.embed([text])


def test_the_local_embedder_names_the_model_it_is():
    from policy_grapher.embedding.local import LocalEmbedder

    embedder = LocalEmbedder(model="sentence-transformers/all-MiniLM-L6-v2")
    assert embedder.model_id == "local:sentence-transformers/all-MiniLM-L6-v2"


# --- the index and its provenance ---------------------------------------------


def _seed_chunks(driver, database, *, version_id="v", text="The Director shall notify."):
    driver.execute_query(
        "MERGE (d:Document {slug: 'd', name: 'D'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"vid": version_id},
        database_=database,
    )
    chunks = chunk_pages([f"1.1. A.\n{text}\n"], version_id=version_id)
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=chunks)
    return chunks


@pytest.mark.integration
def test_embedding_records_which_model_produced_the_vectors(clean_graph, database):
    _seed_chunks(clean_graph, database)
    embedder = FakeEmbedder()

    written = embed_chunks(clean_graph, database, version_id="v", embedder=embedder)

    assert written > 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL "
        "RETURN DISTINCT c.embedding_model AS model, size(c.embedding) AS width",
        database_=database,
    )
    assert records[0]["model"] == "fake-a"
    assert records[0]["width"] == 4


@pytest.mark.integration
def test_a_different_model_is_refused_and_both_are_named(clean_graph, database):
    """The most dangerous failure in the phase, because nothing about it looks
    broken: vectors from two embedders are not comparable, and mixing them
    returns quietly wrong neighbours forever."""
    _seed_chunks(clean_graph, database)
    embed_chunks(clean_graph, database, version_id="v", embedder=FakeEmbedder())

    with pytest.raises(EmbeddingModelMismatch) as excinfo:
        embed_chunks(
            clean_graph,
            database,
            version_id="v",
            embedder=FakeEmbedder(model_id="fake-b"),
        )

    message = str(excinfo.value)
    assert "fake-a" in message and "fake-b" in message


@pytest.mark.integration
def test_a_different_width_is_refused(clean_graph, database):
    """Same name, different geometry. The index cannot hold both."""
    _seed_chunks(clean_graph, database)
    embed_chunks(clean_graph, database, version_id="v", embedder=FakeEmbedder())

    with pytest.raises(EmbeddingModelMismatch, match="dimension"):
        embed_chunks(
            clean_graph,
            database,
            version_id="v",
            embedder=FakeEmbedder(model_id="fake-a", dimensions=8),
        )


@pytest.mark.integration
def test_re_embedding_writes_nothing_new(clean_graph, database):
    _seed_chunks(clean_graph, database)
    embedder = FakeEmbedder()

    first = embed_chunks(clean_graph, database, version_id="v", embedder=embedder)
    second = embed_chunks(clean_graph, database, version_id="v", embedder=embedder)

    assert first > 0
    assert second == 0


@pytest.mark.integration
def test_a_chunk_with_no_text_is_skipped(clean_graph, database):
    """An empty string embeds to a real vector that means nothing, and would sit
    in the index as a plausible neighbour for anything."""
    _seed_chunks(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (c:Chunk) SET c.text = '   '", database_=database
    )

    written = embed_chunks(
        clean_graph, database, version_id="v", embedder=FakeEmbedder()
    )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_the_null_embedder_creates_no_index_and_embeds_nothing(clean_graph, database):
    """It has no geometry to declare, so there is no index it could create."""
    _seed_chunks(clean_graph, database)

    written = embed_chunks(
        clean_graph, database, version_id="v", embedder=NullEmbedder()
    )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (i:EmbeddingIndex) RETURN count(i) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_the_index_records_its_provenance(clean_graph, database):
    ensure_vector_index(clean_graph, database, embedder=FakeEmbedder())

    records, _, _ = clean_graph.execute_query(
        "MATCH (i:EmbeddingIndex) RETURN i.model_id AS model, i.dimensions AS dims",
        database_=database,
    )
    assert (records[0]["model"], records[0]["dims"]) == ("fake-a", 4)
