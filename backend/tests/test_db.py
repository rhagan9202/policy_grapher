import pytest
from neo4j import NotificationClassification, RoutingControl
from neo4j.exceptions import ConstraintError

from policy_grapher.db import apply_schema, is_graph_empty

pytestmark = pytest.mark.integration


def test_all_uniqueness_constraints_exist(driver, database):
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names",
        database_=database,
        routing_=RoutingControl.READ,
    )
    names = set(records[0]["names"])
    assert {
        "document_slug_unique",
        "document_name_unique",
        "source_id_unique",
        "chunk_id_unique",
    } <= names


def test_the_chunk_fulltext_index_exists(driver, database):
    """Pins that INDEXES actually gets run, not merely declared: a version of
    apply_schema that still only loops over CONSTRAINTS would leave every test
    querying the index (test_chunks.py) failing at CALL time, but this test
    fails more directly, by name, against SHOW INDEXES.
    """
    records, _, _ = driver.execute_query(
        "SHOW INDEXES YIELD name, type WHERE name = 'chunk_text' "
        "RETURN type AS index_type",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert len(records) == 1
    assert records[0]["index_type"] == "FULLTEXT"


def test_applying_constraints_twice_is_safe(driver, database):
    def constraint_count() -> int:
        records, _, _ = driver.execute_query(
            "SHOW CONSTRAINTS YIELD name RETURN count(name) AS total",
            database_=database,
            routing_=RoutingControl.READ,
        )
        return records[0]["total"]

    apply_schema(driver, database)
    first_count = constraint_count()

    apply_schema(driver, database)
    second_count = constraint_count()

    assert second_count == first_count


def test_duplicate_slug_is_rejected(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'a', name: 'A'})",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    with pytest.raises(ConstraintError):
        clean_graph.execute_query(
            "CREATE (:Document {slug: 'a', name: 'Different'})",
            database_=database,
            routing_=RoutingControl.WRITE,
        )


def test_duplicate_name_is_rejected(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'a', name: 'A'})",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    with pytest.raises(ConstraintError):
        clean_graph.execute_query(
            "CREATE (:Document {slug: 'different', name: 'A'})",
            database_=database,
            routing_=RoutingControl.WRITE,
        )


def test_is_graph_empty_reflects_content(clean_graph, database):
    assert is_graph_empty(clean_graph, database) is True
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'a', name: 'A'})",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    assert is_graph_empty(clean_graph, database) is False


def test_a_graph_holding_only_an_orphan_source_is_empty(
    client_with_auth, driver, database
):
    """Deleting the last document leaves the shared `api` :Source behind.

    "Empty" means no documents: the sole caller is startup auto-ingest, which
    must still load the sample corpus after a create-then-delete round trip.
    Counting every node would let a provenance node the user cannot see block
    the load, and the UI would come up empty until someone called POST /reset.
    """
    created = client_with_auth.post("/documents", json={"name": "Temporary"})
    assert created.status_code == 201
    slug = created.json()["slug"]
    assert client_with_auth.delete(f"/documents/{slug}").status_code == 204

    records, _, _ = driver.execute_query(
        "MATCH (d:Document) RETURN count(d) AS documents",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["documents"] == 0

    records, _, _ = driver.execute_query(
        "MATCH (s:Source) RETURN count(s) AS sources",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["sources"] == 1, "the orphan :Source this test is about is gone"

    assert is_graph_empty(driver, database) is True


@pytest.mark.integration
def test_unrecognised_notifications_are_not_requested(clean_graph, database):
    """Neo4j deletes a property when it is set to null, so an optional field that
    has never once been non-null in a database has no property key — and every
    query naming one warns `01N52`, at WARNING, with the whole query text inline.

    Four of ours are legitimately unwritten on a fresh graph: `previous_statement`
    (only set for MODIFIED changes), `embedding` (the default embedder produces
    none), and `deadline`/`conditions` on an obligation. None is a typo, and none
    resolves on its own, so the notifications are pure noise on a data model built
    around optional fields.

    Turning the class off costs the one thing it also catches — a genuinely
    misspelled property — and that is covered better elsewhere: a typo returns
    null, and these suites assert real values against real containers, so it fails
    a test rather than merely logging.
    """
    _, summary, _ = clean_graph.execute_query(
        "MATCH (n:Document) RETURN n.a_property_nobody_has_ever_written AS x LIMIT 1",
        database_=database,
    )

    unrecognised = [
        status
        for status in summary.gql_status_objects
        if getattr(status, "classification", None) == NotificationClassification.UNRECOGNIZED
    ]
    assert unrecognised == [], (
        "the driver is still requesting UNRECOGNIZED notifications: "
        f"{[s.status_description for s in unrecognised]}"
    )
