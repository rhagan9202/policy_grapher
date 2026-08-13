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
    record = response.json()[0]["d"]
    assert "Document" in record["labels"]
    assert record["properties"]["name"] == "DoDI 3115.14"


@pytest.mark.integration
def test_returning_a_relationship_is_serialised(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH ()-[r:REFERENCES]->() RETURN r LIMIT 1"}
    )

    assert response.json()[0]["r"]["type"] == "REFERENCES"


@pytest.mark.integration
def test_a_temporal_value_survives_serialisation(client_with_graph):
    """No stored value is temporal, but RETURN datetime() is valid Cypher."""
    response = client_with_graph.post("/query", json={"cypher": "RETURN datetime() AS now"})

    assert response.status_code == 200
    assert isinstance(response.json()[0]["now"], str)


@pytest.mark.integration
def test_scalar_aggregates_come_back_plain(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH (d:Document) RETURN count(d) AS total"}
    )

    assert response.json() == [{"total": 438}]


@pytest.mark.integration
def test_writes_are_permitted(client_with_graph):
    """ADR-004: no read-only enforcement in DI-1."""
    client_with_graph.post(
        "/query", json={"cypher": "CREATE (:Document {slug: 'from-query', name: 'From Query'})"}
    )

    assert client_with_graph.get("/documents/from-query").status_code == 200


@pytest.mark.integration
def test_invalid_cypher_is_400_not_500(client_with_graph):
    response = client_with_graph.post("/query", json={"cypher": "NOT VALID CYPHER"})

    assert response.status_code == 400
