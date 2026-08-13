import pytest
from neo4j import RoutingControl
from neo4j.exceptions import ConstraintError

from policy_grapher.db import CONSTRAINTS, apply_constraints, is_graph_empty

pytestmark = pytest.mark.integration


def test_both_uniqueness_constraints_exist(driver, database):
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names",
        database_=database,
        routing_=RoutingControl.READ,
    )
    names = set(records[0]["names"])
    assert {"document_slug_unique", "document_name_unique"} <= names


def test_applying_constraints_twice_is_safe(driver, database):
    apply_constraints(driver, database)
    apply_constraints(driver, database)
    assert len(CONSTRAINTS) == 2


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
