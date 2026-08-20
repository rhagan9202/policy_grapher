import pytest

from policy_grapher.chunking import Chunk, chunk_pages
from policy_grapher.chunks import UnknownVersionError, drop_chunks, write_chunks


def _seed_version(driver, database):
    driver.execute_query(
        "CREATE (d:Document {slug: 'd', name: 'D'})-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: 'v', checksum: 'x', source_uri: 'file:///d.pdf'})",
        database_=database,
    )


def _seed_second_version(driver, database, version_id):
    """A distinct Document/DocumentVersion pair, for tests that need two versions
    in the graph at once to prove an operation is scoped to just one of them."""
    driver.execute_query(
        "CREATE (d:Document {slug: $slug, name: $name})-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: $version_id, checksum: 'x', "
        "source_uri: 'file:///d2.pdf'})",
        slug=f"d-{version_id}",
        name=f"D {version_id}",
        version_id=version_id,
        database_=database,
    )


@pytest.mark.integration
def test_chunks_attach_to_their_version(clean_graph, database):
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        written = session.execute_write(write_chunks, version_id="v", chunks=chunks)

    assert written == len(chunks)
    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v'})-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN c.section_path AS path, c.page AS page",
        database_=database,
    )
    assert records[0]["path"] == ["1.1"]
    assert records[0]["page"] == 1


@pytest.mark.integration
def test_writing_the_same_chunks_twice_creates_nothing_new(clean_graph, database):
    """Deterministic ids make a rebuild idempotent."""
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == len(chunks)


@pytest.mark.integration
def test_dropping_chunks_leaves_the_version_intact(clean_graph, database):
    """The derived layer is droppable; the canonical layer is not touched."""
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)
        dropped = session.execute_write(drop_chunks, version_id="v")

    assert dropped == len(chunks)
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) WITH count(c) AS chunks "
        "MATCH (v:DocumentVersion) RETURN chunks, count(v) AS versions",
        database_=database,
    )
    assert (records[0]["chunks"], records[0]["versions"]) == (0, 1)


@pytest.mark.integration
def test_the_fulltext_index_finds_a_designator(clean_graph, database):
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nSee DoDI 5000.88 for detail.\n"], version_id="v")
    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        'CALL db.index.fulltext.queryNodes("chunk_text", $q) '
        "YIELD node RETURN node.chunk_id AS id",
        {"q": '"DoDI 5000.88"'},
        database_=database,
    )
    assert records


# --- Properties beyond the brief's verbatim cases -------------------------


@pytest.mark.integration
def test_drop_then_write_reproduces_an_identical_graph(clean_graph, database):
    """A true rebuild: drop, then write again, lands on the same ids, the same
    node count, and exactly one HAS_CHUNK edge per chunk — not merely the same
    count reached by some other path (e.g. a drop that silently no-ops, letting
    the second write's MERGE match pre-existing nodes instead of recreating
    them). Asserting zero chunks right after the drop is what rules that out.
    """
    _seed_version(clean_graph, database)
    pages = ["1.1. A.\nAlpha.\n1.2. B.\nBravo.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert len(chunks) >= 2, "need more than one chunk for this to mean anything"

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

        first_ids, _, _ = clean_graph.execute_query(
            "MATCH (c:Chunk) RETURN collect(c.chunk_id) AS ids", database_=database
        )
        first_ids = set(first_ids[0]["ids"])

        session.execute_write(drop_chunks, version_id="v")

        # The drop must have actually removed the nodes, not merely the edges —
        # otherwise the rewrite below would "succeed" by matching leftovers.
        mid_count, _, _ = clean_graph.execute_query(
            "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
        )
        assert mid_count[0]["total"] == 0

        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    second_ids, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN collect(c.chunk_id) AS ids", database_=database
    )
    second_ids = set(second_ids[0]["ids"])
    assert second_ids == first_ids

    counts, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v'})-[r:HAS_CHUNK]->(c:Chunk) "
        "RETURN count(DISTINCT c) AS chunks, count(r) AS edges",
        database_=database,
    )
    assert counts[0]["chunks"] == len(chunks)
    assert counts[0]["edges"] == len(chunks), "no duplicate HAS_CHUNK edges"


@pytest.mark.integration
def test_drop_chunks_is_scoped_to_its_own_version(clean_graph, database):
    """drop_chunks(version_id='v1') must not touch v2's chunks.

    An unscoped delete (e.g. `MATCH (c:Chunk) DETACH DELETE c` with no
    version filter) would pass every other test here, since they only ever
    seed one version. This test seeds two and checks the one not targeted.
    """
    _seed_second_version(clean_graph, database, version_id="v1")
    _seed_second_version(clean_graph, database, version_id="v2")
    chunks_v1 = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v1")
    chunks_v2 = chunk_pages(["1.1. A.\nBravo.\n1.2. B.\nCharlie.\n"], version_id="v2")

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v1", chunks=chunks_v1)
        session.execute_write(write_chunks, version_id="v2", chunks=chunks_v2)

        dropped = session.execute_write(drop_chunks, version_id="v1")

    assert dropped == len(chunks_v1)

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v1'})-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN count(c) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v2'})-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN count(c) AS total",
        database_=database,
    )
    assert records[0]["total"] == len(chunks_v2)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == len(chunks_v2), "v1's chunks are gone; v2's remain — nothing extra"


@pytest.mark.integration
def test_write_chunks_returns_zero_for_an_empty_list(clean_graph, database):
    """Guards the early-return path: an empty chunk list must not touch the
    graph or crash on an empty UNWIND parameter.
    """
    _seed_version(clean_graph, database)

    with clean_graph.session(database=database) as session:
        written = session.execute_write(write_chunks, version_id="v", chunks=[])

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_chunk_text_is_stored_verbatim(clean_graph, database):
    """`c.text` is what the document actually says, byte for byte — a citation
    has to quote it exactly. Constructed directly rather than via chunk_pages
    so the exact bytes are under this test's control: leading and trailing
    whitespace, an internal double space, and an embedded newline. This must
    fail against `.strip()` (removes the leading/trailing spaces), against
    `" ".join(text.split())` (collapses the internal newline and double space),
    and against `text + " "` (adds a trailing byte) — any of the three changes
    what comes back from this exact-equality read.
    """
    _seed_version(clean_graph, database)
    text = "  Leading space,\ninternal  double  space,\nand trailing space.  "
    chunk = Chunk(
        chunk_id="verbatim-text-test-chunk",
        text=text,
        page=1,
        section_path=["1.1"],
        ordinal=0,
    )

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=[chunk])

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk {chunk_id: $chunk_id}) RETURN c.text AS text",
        chunk_id=chunk.chunk_id,
        database_=database,
    )
    assert records[0]["text"] == text


@pytest.mark.integration
def test_ordinal_round_trips(clean_graph, database):
    """Ordinal is what makes chunk order reproducible after a rebuild — assert
    each chunk's stored ordinal matches the one it was written with, keyed by
    chunk_id so this doesn't depend on any particular read-back order.
    """
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n1.2. B.\nBravo.\n"], version_id="v")
    assert len(chunks) >= 2, "need more than one chunk for this to mean anything"

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN c.chunk_id AS chunk_id, c.ordinal AS ordinal",
        database_=database,
    )
    stored = {r["chunk_id"]: r["ordinal"] for r in records}
    for chunk in chunks:
        assert stored[chunk.chunk_id] == chunk.ordinal


@pytest.mark.integration
def test_write_chunks_raises_for_an_unknown_version(clean_graph, database):
    """A version_id that names no :DocumentVersion must not silently no-op.

    The leading `MATCH (v:DocumentVersion {version_id: $version_id})` would
    otherwise match nothing, `UNWIND` would never execute, and a caller
    trusting the old `len(chunks)` return value would believe every chunk was
    written when zero were. No :DocumentVersion is seeded here at all.
    """
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="ghost")

    with (
        clean_graph.session(database=database) as session,
        pytest.raises(UnknownVersionError, match="ghost"),
    ):
        session.execute_write(write_chunks, version_id="ghost", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_write_chunks_return_value_reflects_what_was_actually_written(clean_graph, database):
    """The return value must come from the query result, not from
    `len(chunks)`: two distinct Chunk objects that happen to share a
    chunk_id merge onto the same node, so the true count is 1, not 2. A
    write_chunks that returned `len(chunks)` unconditionally would report 2
    here and fail this assertion.
    """
    _seed_version(clean_graph, database)
    shared_id = "shared-chunk-id-for-this-test"
    first = Chunk(chunk_id=shared_id, text="A", page=1, section_path=["1.1"], ordinal=0)
    second = Chunk(chunk_id=shared_id, text="A", page=1, section_path=["1.1"], ordinal=1)

    with clean_graph.session(database=database) as session:
        written = session.execute_write(write_chunks, version_id="v", chunks=[first, second])

    assert written == 1, "two inputs sharing a chunk_id merge onto one node"

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == 1
