"""Every endpoint SPEC-001 names now exists."""

import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


def test_every_specified_endpoint_responds(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    assert client_with_graph.get("/health").status_code == 200
    assert client_with_graph.get("/graph").status_code == 200
    assert client_with_graph.get("/documents").status_code == 200
    assert client_with_graph.get("/documents/dodd-5000-01").status_code == 200
    assert client_with_graph.post(
        "/query", json={"cypher": "RETURN 1 AS one"}
    ).status_code == 200

    created = client_with_graph.post(
        "/documents", json={"name": "DoDD 9999.01"}
    )
    assert created.status_code == 201
    slug = created.json()["slug"]

    # PUT was removed by ADR-006: a Document has no mutable field.
    assert client_with_graph.put(f"/documents/{slug}", json={"name": "x"}).status_code == 405
    assert client_with_graph.post(
        f"/documents/{slug}/references/dodd-5000-01"
    ).status_code == 204
    assert client_with_graph.delete(
        f"/documents/{slug}/references/dodd-5000-01"
    ).status_code == 204
    assert client_with_graph.delete(f"/documents/{slug}").status_code == 204
    assert client_with_graph.post("/reset").status_code == 200


def test_a_full_round_trip_leaves_the_graph_as_it_started(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    before = client_with_graph.get("/graph", params={"include_external": "true", "limit": 0}).json()

    created = client_with_graph.post(
        "/documents", json={"name": "Temporary Document"}
    ).json()
    client_with_graph.post(f"/documents/{created['slug']}/references/dodd-5000-01")
    client_with_graph.delete(f"/documents/{created['slug']}")

    after = client_with_graph.get("/graph", params={"include_external": "true", "limit": 0}).json()
    assert after == before
