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
def test_returning_a_whole_node_does_not_500(client_with_auth):
    """`MATCH (n) RETURN n` is the first thing a Cypher-fluent user types."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})

    response = client_with_auth.post(
        "/query", json={"cypher": "MATCH (d:Document {slug: 'dodi-3115-14'}) RETURN d"}
    )

    assert response.status_code == 200
    record = response.json()["rows"][0]["d"]
    assert "Document" in record["labels"]
    assert record["properties"]["name"] == "DoDI 3115.14"


@pytest.mark.integration
def test_returning_a_relationship_is_serialised(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})

    response = client_with_auth.post(
        "/query", json={"cypher": "MATCH ()-[r:REFERENCES]->() RETURN r LIMIT 1"}
    )

    assert response.json()["rows"][0]["r"]["type"] == "REFERENCES"


@pytest.mark.integration
def test_a_temporal_value_survives_serialisation(client_with_auth):
    """No stored value is temporal, but RETURN datetime() is valid Cypher."""
    response = client_with_auth.post("/query", json={"cypher": "RETURN datetime() AS now"})

    assert response.status_code == 200
    assert isinstance(response.json()["rows"][0]["now"], str)


@pytest.mark.integration
def test_scalar_aggregates_come_back_plain(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})

    response = client_with_auth.post(
        "/query", json={"cypher": "MATCH (d:Document) RETURN count(d) AS total"}
    )

    body = response.json()
    assert body["rows"] == [{"total": 438}]
    assert body["returned_rows"] == 1
    assert body["truncated"] is False


@pytest.mark.integration
def test_invalid_cypher_is_400_not_500(client_with_auth):
    response = client_with_auth.post("/query", json={"cypher": "NOT VALID CYPHER"})

    assert response.status_code == 400


@pytest.mark.integration
def test_a_write_query_is_rejected_and_changes_nothing(client_with_auth):
    """ADR-009: /query is read-only. The invariant is the graph, not the error string."""
    before = client_with_auth.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]

    response = client_with_auth.post(
        "/query", json={"cypher": "CREATE (:Document {slug: 'x', name: 'X'})"}
    )
    assert response.status_code == 400

    after = client_with_auth.post(
        "/query", json={"cypher": "MATCH (n) RETURN count(n) AS n"}
    ).json()["rows"][0]["n"]
    assert after == before


@pytest.mark.integration
def test_a_runaway_query_stops_at_the_cap_instead_of_being_materialised(
    client_with_auth, monkeypatch
):
    """The cap has to bound the *work*, not just the response.

    A hundred million rows cannot be built in this process inside the transaction
    timeout, so an implementation that fetches everything before capping answers 400
    (timed out) here, and a streaming one answers 200 with `row_cap` rows almost
    immediately. `/query` runs Cypher the caller supplied — the design's motivating
    threat is a query generated from a prompt-injected document.
    """
    monkeypatch.setattr(client_with_auth.app.state.settings, "query_row_cap", 5)

    response = client_with_auth.post(
        "/query", json={"cypher": "UNWIND range(1, 100000000) AS i RETURN i"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["returned_rows"] == 5
    assert body["truncated"] is True


@pytest.mark.integration
def test_the_transaction_timeout_still_bounds_a_slow_query(client_with_auth, monkeypatch):
    """The row cap bounds rows; the timeout bounds work that produces none.

    This aggregates 500 million values into a single row, so streaming cannot cut it
    short — only `QUERY_TIMEOUT_SECONDS`, sent to the server with the query, can.
    Pinned here because the cap's implementation moved from `execute_query` to a
    session, and the timeout travels differently on that path.
    """
    monkeypatch.setattr(client_with_auth.app.state.settings, "query_timeout_seconds", 0.5)

    response = client_with_auth.post(
        "/query", json={"cypher": "UNWIND range(1, 500000000) AS i RETURN count(i)"}
    )

    assert response.status_code == 400


@pytest.mark.integration
def test_a_row_cap_of_zero_means_no_cap(client_with_auth, monkeypatch):
    """Same convention as GRAPH_RENDER_CAP, whose `0` SPEC-001 documents as uncapped.

    The alternative reading — `0` rows, always, `truncated: true` — is silent
    truncation wearing a flag, and the two same-shaped settings would mean opposite
    things.
    """
    monkeypatch.setattr(client_with_auth.app.state.settings, "query_row_cap", 0)

    response = client_with_auth.post(
        "/query", json={"cypher": "UNWIND range(1, 10) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 10
    assert body["truncated"] is False


@pytest.mark.integration
def test_the_row_cap_truncates_and_says_so(client_with_auth, monkeypatch):
    monkeypatch.setattr(client_with_auth.app.state.settings, "query_row_cap", 3)

    response = client_with_auth.post(
        "/query", json={"cypher": "UNWIND range(1, 10) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is True
    assert len(body["rows"]) == 3


@pytest.mark.integration
def test_a_result_under_the_cap_is_not_reported_as_truncated(client_with_auth):
    response = client_with_auth.post(
        "/query", json={"cypher": "UNWIND range(1, 3) AS i RETURN i"}
    )

    body = response.json()
    assert body["returned_rows"] == 3
    assert body["truncated"] is False
