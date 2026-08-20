import pytest

from policy_grapher.query import coerce

SAMPLE = "dod_policy_references_08122026.csv"


# --- coercion, no database ---------------------------------------------

def test_scalars_pass_through_unchanged():
    assert coerce("a") == "a"
    assert coerce(3) == 3
    assert coerce(1.5) == 1.5
    assert coerce(True) is True
    assert coerce(None) is None


def test_nested_collections_are_coerced_element_wise():
    assert coerce([1, ["a", None]]) == [1, ["a", None]]
    assert coerce({"k": [1, 2]}) == {"k": [1, 2]}


def test_a_value_with_no_json_representation_falls_back_to_str():
    class Opaque:
        def __str__(self):
            return "opaque-value"

    assert coerce(Opaque()) == "opaque-value"


# --- against the real driver -------------------------------------------

@pytest.mark.integration
def test_returning_a_whole_node_does_not_500(client_with_graph):
    """`MATCH (n) RETURN n` is the first thing a Cypher-fluent user types."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH (d:Document {slug: 'dodi-3115-14'}) RETURN d"}
    )

    assert response.status_code == 200
    record = response.json()["rows"][0]["d"]
    assert "Document" in record["labels"]
    assert record["properties"]["name"] == "DoDI 3115.14"


@pytest.mark.integration
def test_returning_a_relationship_is_serialised(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH ()-[r:REFERENCES]->() RETURN r LIMIT 1"}
    )

    assert response.json()["rows"][0]["r"]["type"] == "REFERENCES"


@pytest.mark.integration
def test_a_temporal_value_survives_serialisation(client_with_graph):
    """No stored value is temporal, but RETURN datetime() is valid Cypher."""
    response = client_with_graph.post("/query", json={"cypher": "RETURN datetime() AS now"})

    assert response.status_code == 200
    assert isinstance(response.json()["rows"][0]["now"], str)


@pytest.mark.integration
def test_scalar_aggregates_come_back_plain(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH (d:Document) RETURN count(d) AS total"}
    )

    body = response.json()
    assert body["rows"] == [{"total": 438}]
    assert body["returned_rows"] == 1
    assert body["truncated"] is False


@pytest.mark.integration
def test_invalid_cypher_is_400_not_500(client_with_graph):
    response = client_with_graph.post("/query", json={"cypher": "NOT VALID CYPHER"})

    assert response.status_code == 400


@pytest.mark.integration
def test_a_write_query_is_rejected_and_changes_nothing(client_with_graph):
    """ADR-009: /query is read-only. The invariant is the graph, not the error string."""
    before = client_with_graph.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]

    response = client_with_graph.post(
        "/query", json={"cypher": "CREATE (:Document {slug: 'x', name: 'X'})"}
    )
    assert response.status_code == 400

    after = client_with_graph.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]
    assert after == before


@pytest.mark.integration
def test_the_row_cap_truncates_and_says_so(client_with_graph, monkeypatch):
    monkeypatch.setattr(client_with_graph.app.state.settings, "query_row_cap", 3)

    response = client_with_graph.post(
        "/query", json={"cypher": "UNWIND range(1, 10) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is True
    assert len(body["rows"]) == 3


@pytest.mark.integration
def test_a_result_under_the_cap_is_not_reported_as_truncated(client_with_graph):
    response = client_with_graph.post(
        "/query", json={"cypher": "UNWIND range(1, 3) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is False
