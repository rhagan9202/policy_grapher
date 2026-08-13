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
