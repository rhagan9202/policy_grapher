import pytest
from neo4j import RoutingControl

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


@pytest.fixture
def loaded(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    return client_with_auth


def relationship_count(driver, database, source: str, target: str) -> int:
    """Count REFERENCES edges directly in the graph, bypassing the API's
    DISTINCT read path, which would hide duplicate relationships."""
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $source})-[r:REFERENCES]->(:Document {slug: $target}) "
        "RETURN count(r) AS total",
        {"source": source, "target": target},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["total"]


def test_adding_an_edge_shows_up_in_both_directions(loaded):
    response = loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")

    assert response.status_code == 204
    assert "dodi-3115-14" in loaded.get("/documents/dodd-5000-01").json()["references"]
    assert "dodd-5000-01" in loaded.get("/documents/dodi-3115-14").json()["referenced_by"]


def test_adding_the_same_edge_twice_is_idempotent(loaded, driver, database):
    loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")
    loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")

    references = loaded.get("/documents/dodd-5000-01").json()["references"]
    assert references.count("dodi-3115-14") == 1
    assert relationship_count(driver, database, "dodd-5000-01", "dodi-3115-14") == 1


def test_a_self_reference_is_400(loaded):
    response = loaded.post("/documents/dodd-5000-01/references/dodd-5000-01")

    assert response.status_code == 400
    assert "dodd-5000-01" not in loaded.get("/documents/dodd-5000-01").json()["references"]


def test_an_unknown_endpoint_is_404(loaded):
    assert loaded.post("/documents/no-such-doc/references/dodi-3115-14").status_code == 404
    assert loaded.post("/documents/dodd-5000-01/references/no-such-doc").status_code == 404


def test_removing_an_edge_leaves_both_documents(loaded):
    before = loaded.get("/documents/dodd-5000-01").json()["references"]
    target = before[0]

    assert loaded.delete(f"/documents/dodd-5000-01/references/{target}").status_code == 204

    assert target not in loaded.get("/documents/dodd-5000-01").json()["references"]
    assert loaded.get(f"/documents/{target}").status_code == 200
    assert loaded.get("/documents/dodd-5000-01").status_code == 200


def test_removing_an_absent_edge_is_still_204(loaded):
    """The contract is 'this edge does not exist afterwards'."""
    response = loaded.delete("/documents/dodi-3115-14/references/dodd-5000-01")
    assert response.status_code == 204
