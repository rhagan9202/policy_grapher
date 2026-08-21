import pytest
from neo4j.exceptions import CypherSyntaxError

from policy_grapher.documents import (
    allocate_slugs,
    create_document,
    list_documents,
    reconcile_slugs,
)
from policy_grapher.slugs import assign_slugs, hash_suffix

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"

MIL_A = "Military Standard 882E"
MIL_B = "Military-Standard 882E"
MIL_BASE = "military-standard-882e"


@pytest.fixture
def loaded(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    return client_with_auth


def test_list_returns_every_document_ordered_by_slug(loaded):
    body = loaded.get("/documents").json()

    assert len(body) == 438
    slugs = [doc["slug"] for doc in body]
    assert slugs == sorted(slugs)


def test_list_distinguishes_corpus_from_external(loaded):
    body = loaded.get("/documents").json()

    corpus = [doc for doc in body if not doc["is_external"]]
    external = [doc for doc in body if doc["is_external"]]

    assert len(corpus) == 23
    assert len(external) == 415


def test_get_one_returns_both_directions_as_slugs(loaded):
    body = loaded.get("/documents/dodi-3115-14").json()

    assert body["slug"] == "dodi-3115-14"
    assert body["name"] == "DoDI 3115.14"
    assert body["is_external"] is False
    assert "public-law-116-92" in body["references"]
    assert body["references"] == sorted(body["references"])
    assert body["referenced_by"] == sorted(body["referenced_by"])


def test_an_external_document_is_referenced_but_references_nothing(loaded):
    body = loaded.get("/documents/public-law-116-92").json()

    assert body["is_external"] is True
    assert body["references"] == []
    assert "dodi-3115-14" in body["referenced_by"]


def test_reference_totals_match_the_corpus(loaded):
    body = loaded.get("/documents").json()

    assert sum(len(doc["references"]) for doc in body) == 672
    assert sum(len(doc["referenced_by"]) for doc in body) == 672


def test_unknown_slug_is_404(loaded):
    assert loaded.get("/documents/no-such-document").status_code == 404


def test_create_returns_201_with_a_generated_slug(client_with_auth):
    response = client_with_auth.post(
        "/documents", json={"name": "DoDD 9999.01"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "dodd-9999-01"
    assert body["is_external"] is False
    assert body["references"] == []
    assert body["referenced_by"] == []


def test_create_rejects_a_duplicate_name_with_409(client_with_auth):
    payload = {"name": "DoDD 9999.01"}
    client_with_auth.post("/documents", json=payload)

    response = client_with_auth.post("/documents", json=payload)

    assert response.status_code == 409


def test_a_contested_slug_suffixes_the_newcomer_and_leaves_the_incumbent(client_with_auth):
    """ADR-005: the incumbent keeps its bare slug."""
    first = client_with_auth.post(
        "/documents", json={"name": "Military Standard 882E"}
    ).json()
    second = client_with_auth.post(
        "/documents", json={"name": "Military-Standard 882E"}
    ).json()

    assert first["slug"] == "military-standard-882e"
    assert second["slug"].startswith("military-standard-882e-")
    assert second["slug"] != first["slug"]
    # The incumbent is untouched.
    assert client_with_auth.get("/documents/military-standard-882e").json()["name"] == (
        "Military Standard 882E"
    )


def test_create_rejects_an_empty_name(client_with_auth):
    response = client_with_auth.post(
        "/documents", json={"name": ""}
    )
    assert response.status_code == 422


def test_put_is_no_longer_a_route(loaded):
    """ADR-006: reference_role was PUT's only mutable field; renaming is delete+recreate."""
    response = loaded.put("/documents/dodi-3115-14", json={"name": "DoDI 3115.14"})

    assert response.status_code == 405


def test_delete_removes_the_document_and_its_edges(loaded):
    before = loaded.get("/documents/dodd-5000-01").json()
    assert before["references"]

    assert loaded.delete("/documents/dodd-5000-01").status_code == 204

    assert loaded.get("/documents/dodd-5000-01").status_code == 404
    # Its former targets survive, minus the edge.
    survivor = loaded.get(f"/documents/{before['references'][0]}").json()
    assert "dodd-5000-01" not in survivor["referenced_by"]


def _count(driver, database, cypher):
    records, _, _ = driver.execute_query(cypher, database_=database)
    return records[0]["total"]


def test_deleting_a_document_takes_its_versions_and_chunks_with_it(
    client_with_auth, clean_graph, database
):
    """`DETACH DELETE d` removes the :Document and nothing below it. Its
    :DocumentVersion nodes survive, and since phase 2 so does every :Chunk hanging
    off them — 253 of them for `818001m.pdf` — unreachable through
    `GET /documents/{slug}/chunks`, which anchors on the :Document.
    """
    doomed = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"}).json()
    kept = client_with_auth.post("/ingest", json={"filename": "500088p.pdf"}).json()
    doomed_slug = doomed["document"]["slug"]
    kept_slug = kept["document"]["slug"]

    kept_chunks_before = len(client_with_auth.get(f"/documents/{kept_slug}/chunks").json())
    assert len(client_with_auth.get(f"/documents/{doomed_slug}/chunks").json()) > 0
    assert kept_chunks_before > 0

    assert client_with_auth.delete(f"/documents/{doomed_slug}").status_code == 204

    orphan_versions = _count(
        clean_graph,
        database,
        "MATCH (v:DocumentVersion) WHERE NOT (:Document)-[:HAS_VERSION]->(v) "
        "RETURN count(v) AS total",
    )
    # "Orphan" means unreachable from any :Document — a chunk still hanging off a
    # surviving-but-orphaned version counts, since every route anchors on the
    # :Document and nothing can reach it.
    orphan_chunks = _count(
        clean_graph,
        database,
        "MATCH (c:Chunk) "
        "WHERE NOT (:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:HAS_CHUNK]->(c) "
        "RETURN count(c) AS total",
    )
    assert (orphan_versions, orphan_chunks) == (0, 0)
    # The other document's derived layer is untouched: the delete is scoped, not global.
    assert len(client_with_auth.get(f"/documents/{kept_slug}/chunks").json()) == kept_chunks_before


def test_delete_an_unknown_slug_is_404(loaded):
    assert loaded.delete("/documents/no-such-document").status_code == 404


class TestAllocateSlugs:
    """The document path's batch allocation, exercised directly rather than
    through `ingest_document`'s PDF extraction and graph writes."""

    def test_an_already_stored_name_keeps_the_slug_it_holds(self, clean_graph, database):
        create_document(clean_graph, database, MIL_A)

        assert allocate_slugs(clean_graph, database, [MIL_A]) == {MIL_A: MIL_BASE}

    def test_a_stored_name_keeps_a_slug_that_is_already_suffixed(
        self, clean_graph, database
    ):
        create_document(clean_graph, database, MIL_A)
        create_document(clean_graph, database, MIL_B)
        suffixed = f"{MIL_BASE}-{hash_suffix(MIL_B)}"

        assert allocate_slugs(clean_graph, database, [MIL_B]) == {MIL_B: suffixed}

    def test_two_new_names_contesting_one_base_resolve_distinctly(
        self, clean_graph, database
    ):
        """Neither exists yet, so the database cannot separate them: the first in
        the batch keeps the base, the second takes the suffix."""
        assigned = allocate_slugs(clean_graph, database, [MIL_A, MIL_B])

        assert assigned == {MIL_A: MIL_BASE, MIL_B: f"{MIL_BASE}-{hash_suffix(MIL_B)}"}
        assert len(set(assigned.values())) == 2

    def test_batch_order_decides_which_of_two_new_names_stays_bare(
        self, clean_graph, database
    ):
        assigned = allocate_slugs(clean_graph, database, [MIL_B, MIL_A])

        assert assigned == {MIL_B: MIL_BASE, MIL_A: f"{MIL_BASE}-{hash_suffix(MIL_A)}"}

    def test_a_new_name_contesting_a_stored_one_takes_the_suffix(
        self, clean_graph, database
    ):
        """ADR-005 decision 2: the incumbent's bare slug never moves."""
        create_document(clean_graph, database, MIL_A)

        assigned = allocate_slugs(clean_graph, database, [MIL_B])

        assert assigned == {MIL_B: f"{MIL_BASE}-{hash_suffix(MIL_B)}"}
        stored = clean_graph.execute_query(
            "MATCH (d:Document {name: $name}) RETURN d.slug AS slug",
            {"name": MIL_A},
            database_=database,
        ).records
        assert stored[0]["slug"] == MIL_BASE

    def test_a_name_repeated_in_the_batch_is_resolved_once(self, clean_graph, database):
        assert allocate_slugs(clean_graph, database, [MIL_A, MIL_A]) == {MIL_A: MIL_BASE}

    def test_an_empty_batch_allocates_nothing(self, clean_graph, database):
        assert allocate_slugs(clean_graph, database, []) == {}


class TestReconcileSlugs:
    """The manifest path's allocation, reconciled against what is already stored."""

    def test_on_an_empty_graph_it_is_exactly_assign_slugs(self, clean_graph, database):
        names = [MIL_A, MIL_B, "DoDD 5000.01"]

        assert reconcile_slugs(clean_graph, database, names) == assign_slugs(names)

    def test_a_stored_name_keeps_its_slug_and_its_contender_is_suffixed(
        self, clean_graph, database
    ):
        """Without this, both contenders would be re-slugged over the name set and
        the stored one would be merged in at a slug it does not hold."""
        create_document(clean_graph, database, MIL_B)

        assigned = reconcile_slugs(clean_graph, database, [MIL_A, MIL_B])

        assert assigned[MIL_B] == MIL_BASE
        assert assigned[MIL_A] == f"{MIL_BASE}-{hash_suffix(MIL_A)}"

    def test_a_new_name_never_takes_a_slug_a_stored_document_holds(
        self, clean_graph, database
    ):
        """The stored document is not in the manifest at all, so the name set alone
        would hand its base slug straight to the newcomer."""
        create_document(clean_graph, database, MIL_A)

        assigned = reconcile_slugs(clean_graph, database, [MIL_B])

        assert assigned == {MIL_B: f"{MIL_BASE}-{hash_suffix(MIL_B)}"}


def test_documents_no_longer_carry_a_reference_role(loaded):
    """ADR-006: a document's position relative to others is a fact about edges."""
    corpus = loaded.get("/documents/dodd-5000-01").json()
    external = loaded.get("/documents/public-law-116-283").json()

    assert "reference_role" not in corpus
    assert "reference_role" not in external
    # is_external is what distinguishes them now.
    assert corpus["is_external"] is False
    assert external["is_external"] is True


def test_a_created_document_is_described_by_the_api(client_with_auth, driver, database):
    """ADR-007: a user asserting a document exists is provenance."""
    from neo4j import RoutingControl

    created = client_with_auth.post("/documents", json={"name": "Hand Made Doc"}).json()

    records, _, _ = driver.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document {slug: $slug}) RETURN s.id AS id, s.kind AS kind",
        {"slug": created["slug"]},
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "api"
    assert records[0]["kind"] == "api"


def test_a_created_document_is_not_external(client_with_auth):
    created = client_with_auth.post("/documents", json={"name": "Hand Made Doc"}).json()

    assert created["is_external"] is False
    assert client_with_auth.get(f"/documents/{created['slug']}").json()["is_external"] is False


def test_every_created_document_shares_one_api_source(client_with_auth, driver, database):
    from neo4j import RoutingControl

    client_with_auth.post("/documents", json={"name": "First Hand Made"})
    client_with_auth.post("/documents", json={"name": "Second Hand Made"})

    records, _, _ = driver.execute_query(
        "MATCH (s:Source {kind: 'api'}) RETURN count(s) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_creating_a_document_rolls_back_when_a_later_write_fails(
    clean_graph, database, monkeypatch
):
    """STORY-038. The four writes must commit together or not at all.

    Failure is provoked by making the *last* statement invalid Cypher, so a real
    server-side error arrives partway through a real transaction — nothing here
    mocks the driver. Under the original four-auto-commit implementation the
    :Document is already committed by the time that error lands, and it survives
    as a node with no provenance and no :External label, which nothing
    re-refreshes: the next manifest citing that name silently demotes it and it
    vanishes from the default graph view.
    """
    from policy_grapher import documents as documents_module

    monkeypatch.setattr(documents_module, "REFRESH_EXTERNAL", "RETURN this_is_not_cypher(")

    with pytest.raises(CypherSyntaxError):
        create_document(clean_graph, database, "DoDD 9999.99")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: 'DoDD 9999.99'}) RETURN count(d) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0, (
        "the document was committed before the failing statement — the writes are "
        "not in one transaction"
    )


@pytest.mark.integration
def test_a_listed_document_reports_how_many_editions_it_has(clean_graph, database):
    """STORY-040. Triage can only compare a document that has editions, and 439
    of the sample corpus's 440 have none — so the picker needs to know which,
    without fetching versions for every document one at a time.
    """
    clean_graph.execute_query(
        "CREATE (a:Document {slug: 'has-editions', name: 'DoDD 5000.01'})"
        "-[:HAS_VERSION]->(:DocumentVersion {version_id: 'v1'}) "
        "CREATE (a)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'v2'}) "
        "CREATE (:Document {slug: 'no-editions', name: 'Public Law 116-92'})",
        database_=database,
    )

    by_slug = {d.slug: d for d in list_documents(clean_graph, database)}

    assert by_slug["has-editions"].version_count == 2
    assert by_slug["no-editions"].version_count == 0
