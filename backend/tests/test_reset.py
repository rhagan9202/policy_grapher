import pytest
from neo4j import RoutingControl

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


def node_count(driver, database) -> int:
    records, _, _ = driver.execute_query(
        "MATCH (n) RETURN count(n) AS n",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["n"]


def test_reset_empties_a_loaded_graph_and_reports_counts(client_with_auth, driver, database):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    # 438 :Document nodes from the corpus plus 1 :Source node recording the
    # manifest ingest that described them (see sources/provenance.py).
    assert node_count(driver, database) == 439

    response = client_with_auth.post("/reset")

    assert response.status_code == 200
    # 672 :REFERENCES edges from the corpus plus 23 :DESCRIBES edges from the
    # one :Source node to every document it described.
    assert response.json() == {"nodes_deleted": 439, "relationships_deleted": 695}
    assert node_count(driver, database) == 0


def test_reset_on_an_empty_graph_reports_zeroes(client_with_auth, driver, database):
    response = client_with_auth.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"nodes_deleted": 0, "relationships_deleted": 0}


def test_reset_does_not_retrigger_auto_ingest(client_with_auth, driver, database):
    """Auto-ingest is a startup check. Emptying the graph must not reload it."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    client_with_auth.post("/reset")

    client_with_auth.get("/health")

    assert node_count(driver, database) == 0
