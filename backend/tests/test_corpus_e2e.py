"""STORY-012: the sample DoD corpus loads and renders end to end."""

import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


def test_sample_corpus_loads_and_serves_a_legible_corpus_view(client_with_auth):
    ingest = client_with_auth.post("/ingest", json={"filename": SAMPLE}).json()
    assert ingest["nodes_created"] == 438
    assert ingest["relationships_created"] == 672
    assert ingest["self_references_skipped"] == 4
    assert len(ingest["suspected_duplicates"]) == 2

    default = client_with_auth.get("/graph").json()
    assert default["returned_nodes"] == 23
    assert default["total_nodes"] == 23
    assert default["truncated"] is False
    assert len(default["edges"]) == 72
    assert all(node["is_external"] is False for node in default["nodes"])

    full = client_with_auth.get(
        "/graph", params={"include_external": "true"}
    ).json()
    assert full["total_nodes"] == 438
    assert full["returned_nodes"] == 300
    assert full["truncated"] is True

    uncapped = client_with_auth.get(
        "/graph", params={"include_external": "true", "limit": 0}
    ).json()
    assert uncapped["returned_nodes"] == 438
    assert uncapped["truncated"] is False
    assert len(uncapped["edges"]) == 672


def test_every_returned_node_has_a_usable_slug(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    body = client_with_auth.get(
        "/graph", params={"include_external": "true", "limit": 0}
    ).json()

    slugs = [node["id"] for node in body["nodes"]]
    assert len(set(slugs)) == 438
    for slug in slugs:
        assert slug
        assert "/" not in slug
        assert " " not in slug
        assert slug == slug.lower()


def test_reingesting_leaves_the_rendered_graph_identical(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    before = client_with_auth.get(
        "/graph", params={"include_external": "true", "limit": 300}
    ).json()

    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    after = client_with_auth.get(
        "/graph", params={"include_external": "true", "limit": 300}
    ).json()

    assert before == after
