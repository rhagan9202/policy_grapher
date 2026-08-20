import pytest

from policy_grapher.chunking import PREAMBLE, Chunk, chunk_pages
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
def test_rewriting_a_chunk_id_replaces_what_it_holds(clean_graph, database):
    """`write_chunks` is authoritative for the chunks it is given.

    A chunk id is a hash of where the chunk sits in the document's structure, not
    of its text, so an edited edition ingested under the same version_id
    legitimately reaches an existing chunk_id carrying different text. Under
    `ON CREATE SET` the new text is silently discarded and the graph keeps
    yesterday's passage under today's id — a wrong quotation, which is the one
    failure a verbatim-text store cannot tolerate. `SET` makes the last write
    win; ingest's drop-before-write ordering is then a second line of defence
    rather than the only one.
    """
    _seed_version(clean_graph, database)
    before = Chunk(chunk_id="c1", text="Old passage.", page=1, section_path=["1"], ordinal=0)
    after = Chunk(chunk_id="c1", text="New passage.", page=4, section_path=["1", "1.2"], ordinal=7)

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=[before])
        session.execute_write(write_chunks, version_id="v", chunks=[after])

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk {chunk_id: 'c1'}) "
        "RETURN c.text AS text, c.page AS page, c.section_path AS path, c.ordinal AS ordinal",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["text"] == "New passage."
    assert (records[0]["page"], records[0]["path"], records[0]["ordinal"]) == (
        4,
        ["1", "1.2"],
        7,
    )


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


# --- Task 3: chunking connected to ingest, and exposed -------------------


@pytest.mark.integration
def test_ingesting_a_pdf_stores_its_text(client_with_auth):
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = response.json()["document"]["slug"]

    chunks = client_with_auth.get(f"/documents/{slug}/chunks")
    assert chunks.status_code == 200
    body = chunks.json()
    assert body, "a real DoD issuance must produce at least one chunk"
    assert all(c["text"].strip() for c in body)
    assert all(c["page"] >= 1 for c in body)
    assert any(c["section_path"] != ["(preamble)"] for c in body), (
        "every chunk landing in the preamble means section detection found nothing"
    )


@pytest.mark.integration
def test_page_numbers_are_real_and_varied(client_with_auth):
    """A chunk's `page` is how a citation points a reviewer at the document. If
    `chunk_pages` were fed the whole document as one page (e.g. `[text_of(path)]`
    instead of the real per-page list `sources.pdf.pages_of` now produces), every
    chunk would come back `page=1` and the anchor would be worthless. 500001p.pdf
    runs well past one page, so a correct pipeline must report more than one
    distinct page across its chunks.
    """
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = response.json()["document"]["slug"]

    chunks = client_with_auth.get(f"/documents/{slug}/chunks").json()
    pages = {c["page"] for c in chunks}
    assert len(pages) > 1, f"every chunk landed on the same page: {pages}"


@pytest.mark.integration
def test_manifest_ingest_creates_no_chunks(client_with_auth, driver, database):
    """The manifest (CSV) path states no text and no version: `write_chunks`
    must never be reached for it. A document introduced only by the manifest
    has no `:DocumentVersion` for a chunk to attach to, so this pins the
    invariant directly against the graph rather than trusting that no route
    happens to expose a stray chunk.
    """
    response = client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )
    assert response.status_code == 200

    records, _, _ = driver.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_reingesting_an_unchanged_pdf_keeps_one_set_of_chunks(client_with_auth):
    """DI-1's re-ingest-is-a-no-op invariant, extended to the derived layer:
    posting the identical file twice must not double the chunk count or mint a
    second, parallel set of ids.
    """
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = first.json()["document"]["slug"]
    first_chunks = client_with_auth.get(f"/documents/{slug}/chunks").json()
    assert first_chunks, "the fixture PDF must produce at least one chunk"

    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    second_chunks = client_with_auth.get(f"/documents/{slug}/chunks").json()

    assert len(second_chunks) == len(first_chunks)
    assert {c["chunk_id"] for c in second_chunks} == {c["chunk_id"] for c in first_chunks}


@pytest.mark.integration
def test_a_chunker_change_replaces_rather_than_duplicates_chunks(client_with_auth, monkeypatch):
    """The scenario an identical re-ingest cannot exercise: chunk ids are a pure
    function of (version_id, section_path, ordinal), so an *unchanged* chunker
    naturally re-merges onto the same nodes whether or not `_write_document`
    drops first. `write_chunks` alone (no `drop_chunks`) would still pass
    `test_reingesting_an_unchanged_pdf_keeps_one_set_of_chunks` above.

    This monkeypatches `chunk_pages` itself to return a *different* chunk set on
    the second ingest of the same file — same version_id (same bytes, same
    checksum), different output, exactly the "a chunker improvement must not
    leave the previous run's chunks orphaned" scenario the brief names. Only
    `drop` then `write` clears the first run's chunk before the second lands.
    """
    from policy_grapher import ingest as ingest_module
    from policy_grapher.chunking import Chunk

    calls = {"n": 0}

    def fake_chunk_pages(pages, *, version_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return [
                Chunk(
                    chunk_id="run-one-only",
                    text="first pass",
                    page=1,
                    section_path=[PREAMBLE],
                    ordinal=0,
                )
            ]
        return [
            Chunk(
                chunk_id="run-two-only",
                text="second pass",
                page=1,
                section_path=[PREAMBLE],
                ordinal=0,
            )
        ]

    monkeypatch.setattr(ingest_module, "chunk_pages", fake_chunk_pages)

    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = first.json()["document"]["slug"]
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    chunks = client_with_auth.get(f"/documents/{slug}/chunks").json()
    ids = {c["chunk_id"] for c in chunks}
    assert ids == {"run-two-only"}, (
        "the first run's chunk must be dropped, not left beside the new one"
    )


@pytest.mark.integration
def test_chunks_route_orders_by_ordinal(client_with_auth, clean_graph, database):
    """Written in a shuffled order that is neither ascending nor its own
    reverse, so a passing assertion can only come from the route's explicit
    `ORDER BY c.ordinal` in `LIST_CHUNKS`.

    A first draft of this test wrote chunks in reverse-of-ordinal order to
    defeat "Neo4j happens to return a simple, unordered `MATCH` in insertion
    order" — but for `MATCH (v)-[:HAS_CHUNK]->(c)` specifically, the
    unordered traversal this driver/server version returns is itself
    reverse-of-insertion. Writing in reverse order therefore came back out in
    ascending order with no `ORDER BY` at all: two reversals cancelling out,
    so the test passed whether or not the clause existed — confirmed by
    deleting `ORDER BY c.ordinal` from `LIST_CHUNKS` and watching this test
    still pass. A shuffle that is neither the ascending target nor its
    reverse defeats both possible natural orders at once, however this
    Neo4j version happens to traverse an unordered match.
    """
    _seed_version(clean_graph, database)
    pages = ["1.1. A.\nAlpha.\n1.2. B.\nBravo.\n1.3. C.\nCharlie.\n1.4. D.\nDelta.\n1.5. E.\nEcho.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert len(chunks) >= 5, "need enough chunks that ascending, descending, and shuffled differ"

    ascending = [c.ordinal for c in chunks]
    shuffled = [chunks[2], chunks[4], chunks[1], chunks[3], chunks[0], *chunks[5:]]
    write_order = [c.ordinal for c in shuffled]
    assert write_order not in (ascending, list(reversed(ascending))), (
        "the write order itself must be neither ascending nor descending, or this "
        "test cannot distinguish an explicit ORDER BY from a lucky traversal order"
    )

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=shuffled)

    body = client_with_auth.get("/documents/d/chunks").json()
    ordinals = [c["ordinal"] for c in body]
    assert ordinals == ascending


@pytest.mark.integration
def test_chunks_route_defaults_to_the_newest_version_and_can_be_pinned(
    client_with_auth, clean_graph, database
):
    """`version_id` omitted resolves to the newest edition; passed explicitly,
    it pins one version even while a newer one exists in the same graph.
    """
    clean_graph.execute_query(
        "CREATE (d:Document {slug: 's', name: 'S'})"
        "-[:HAS_VERSION]->(:DocumentVersion {version_id: 'v-old', "
        "effective_date: '2020-01-01', checksum: 'a', source_uri: 'file:///a.pdf'})",
        database_=database,
    )
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 's'}) CREATE (d)-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: 'v-new', effective_date: '2024-01-01', "
        "checksum: 'b', source_uri: 'file:///b.pdf'})",
        database_=database,
    )
    old_chunks = chunk_pages(["1.1. Old.\nOld body.\n"], version_id="v-old")
    new_chunks = chunk_pages(["1.1. New.\nNew body.\n"], version_id="v-new")
    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v-old", chunks=old_chunks)
        session.execute_write(write_chunks, version_id="v-new", chunks=new_chunks)

    default = client_with_auth.get("/documents/s/chunks").json()
    assert {c["chunk_id"] for c in default} == {c.chunk_id for c in new_chunks}

    pinned = client_with_auth.get("/documents/s/chunks", params={"version_id": "v-old"}).json()
    assert {c["chunk_id"] for c in pinned} == {c.chunk_id for c in old_chunks}


@pytest.mark.integration
def test_chunks_route_rejects_an_unauthenticated_caller(client_with_graph):
    response = client_with_graph.get("/documents/some-slug/chunks")
    assert response.status_code == 401
