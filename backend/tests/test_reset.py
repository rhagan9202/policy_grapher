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


def test_reset_empties_a_loaded_graph_and_reports_counts(client_with_graph, driver, database):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    assert node_count(driver, database) == 438

    response = client_with_graph.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"nodes_deleted": 438, "relationships_deleted": 672}
    assert node_count(driver, database) == 0


def test_reset_on_an_empty_graph_reports_zeroes(client_with_graph, driver, database):
    response = client_with_graph.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"nodes_deleted": 0, "relationships_deleted": 0}


def test_reset_does_not_retrigger_auto_ingest(client_with_graph, driver, database):
    """Auto-ingest is a startup check. Emptying the graph must not reload it."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    client_with_graph.post("/reset")

    client_with_graph.get("/health")

    assert node_count(driver, database) == 0
