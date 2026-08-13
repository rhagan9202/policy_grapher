import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


@pytest.fixture
def loaded(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    return client_with_graph


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
    assert all(doc["reference_role"] is not None for doc in corpus)
    assert all(doc["reference_role"] is None for doc in external)


def test_get_one_returns_both_directions_as_slugs(loaded):
    body = loaded.get("/documents/dodi-3115-14").json()

    assert body["slug"] == "dodi-3115-14"
    assert body["name"] == "DoDI 3115.14"
    assert body["reference_role"] == "Sub-Reference"
    assert body["is_external"] is False
    assert "public-law-116-92" in body["references"]
    assert body["references"] == sorted(body["references"])
    assert body["referenced_by"] == sorted(body["referenced_by"])


def test_an_external_document_is_referenced_but_references_nothing(loaded):
    body = loaded.get("/documents/public-law-116-92").json()

    assert body["is_external"] is True
    assert body["reference_role"] is None
    assert body["references"] == []
    assert "dodi-3115-14" in body["referenced_by"]


def test_reference_totals_match_the_corpus(loaded):
    body = loaded.get("/documents").json()

    assert sum(len(doc["references"]) for doc in body) == 672
    assert sum(len(doc["referenced_by"]) for doc in body) == 672


def test_unknown_slug_is_404(loaded):
    assert loaded.get("/documents/no-such-document").status_code == 404


def test_create_returns_201_with_a_generated_slug(client_with_graph):
    response = client_with_graph.post(
        "/documents", json={"name": "DoDD 9999.01", "reference_role": "Root Reference"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "dodd-9999-01"
    assert body["is_external"] is False
    assert body["references"] == []
    assert body["referenced_by"] == []


def test_create_rejects_a_duplicate_name_with_409(client_with_graph):
    payload = {"name": "DoDD 9999.01", "reference_role": "Root Reference"}
    client_with_graph.post("/documents", json=payload)

    response = client_with_graph.post("/documents", json=payload)

    assert response.status_code == 409


def test_a_contested_slug_suffixes_the_newcomer_and_leaves_the_incumbent(client_with_graph):
    """ADR-005: the incumbent keeps its bare slug."""
    first = client_with_graph.post(
        "/documents", json={"name": "Military Standard 882E", "reference_role": "Sub-Reference"}
    ).json()
    second = client_with_graph.post(
        "/documents", json={"name": "Military-Standard 882E", "reference_role": "Sub-Reference"}
    ).json()

    assert first["slug"] == "military-standard-882e"
    assert second["slug"].startswith("military-standard-882e-")
    assert second["slug"] != first["slug"]
    # The incumbent is untouched.
    assert client_with_graph.get("/documents/military-standard-882e").json()["name"] == (
        "Military Standard 882E"
    )


def test_create_rejects_an_empty_name(client_with_graph):
    response = client_with_graph.post(
        "/documents", json={"name": "", "reference_role": "Root Reference"}
    )
    assert response.status_code == 422


def test_update_changes_only_the_reference_role(loaded):
    response = loaded.put(
        "/documents/dodi-3115-14",
        json={"name": "DoDI 3115.14", "reference_role": "Root Reference"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reference_role"] == "Root Reference"
    assert body["name"] == "DoDI 3115.14"
    # Relationships survive the edit.
    assert "public-law-116-92" in body["references"]


def test_update_with_a_mismatched_name_is_400(loaded):
    """SPEC-001's Definition of Done names this case explicitly."""
    response = loaded.put(
        "/documents/dodi-3115-14",
        json={"name": "Something Else", "reference_role": "Root Reference"},
    )

    assert response.status_code == 400
    assert loaded.get("/documents/dodi-3115-14").json()["reference_role"] == "Sub-Reference"


def test_update_on_an_external_document_is_400(loaded):
    """External documents have no reference_role by definition (ADR-002)."""
    response = loaded.put(
        "/documents/public-law-116-92",
        json={"name": "Public Law 116-92", "reference_role": "Root Reference"},
    )

    assert response.status_code == 400
    assert loaded.get("/documents/public-law-116-92").json()["reference_role"] is None


def test_update_an_unknown_slug_is_404(loaded):
    response = loaded.put(
        "/documents/no-such-document",
        json={"name": "Whatever", "reference_role": "Root Reference"},
    )
    assert response.status_code == 404


def test_delete_removes_the_document_and_its_edges(loaded):
    before = loaded.get("/documents/dodd-5000-01").json()
    assert before["references"]

    assert loaded.delete("/documents/dodd-5000-01").status_code == 204

    assert loaded.get("/documents/dodd-5000-01").status_code == 404
    # Its former targets survive, minus the edge.
    survivor = loaded.get(f"/documents/{before['references'][0]}").json()
    assert "dodd-5000-01" not in survivor["referenced_by"]


def test_delete_an_unknown_slug_is_404(loaded):
    assert loaded.delete("/documents/no-such-document").status_code == 404
