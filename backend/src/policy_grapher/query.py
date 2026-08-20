"""Read-only Cypher passthrough.

Read routing, a transaction timeout and a row cap, per ADR-009. Mutation moved to
authenticated routes when ADR-004's local-only assumption stopped holding.
"""

from collections.abc import Mapping
from typing import Any, LiteralString, cast

from neo4j import Driver, EagerResult, Query, RoutingControl
from neo4j.graph import Node, Path, Relationship

from policy_grapher.models import JSON_SCALARS, JSONValue, QueryResult


def coerce(value: object) -> JSONValue:
    """Turn driver values into something FastAPI can serialise.

    `MATCH (n) RETURN n` yields Node objects, and `RETURN datetime()` yields a
    temporal — neither is JSON-serialisable, and both are things a user types.
    """
    if isinstance(value, Node):
        return {"labels": sorted(value.labels), "properties": dict(value)}
    if isinstance(value, Relationship):
        return {"type": value.type, "properties": dict(value)}
    if isinstance(value, Path):
        return {
            "nodes": [coerce(node) for node in value.nodes],
            "relationships": [coerce(rel) for rel in value.relationships],
        }
    if isinstance(value, list):
        return [coerce(item) for item in value]
    if isinstance(value, dict):
        return {key: coerce(item) for key, item in value.items()}
    if value is None or isinstance(value, JSON_SCALARS):
        return value
    return str(value)


def run_cypher(
    driver: Driver,
    database: str,
    cypher: str,
    *,
    row_cap: int,
    timeout_seconds: float,
) -> QueryResult:
    # READ routing: Neo4j rejects a write attempted in a read transaction, so the
    # enforcement is the database's, not a regex over the query text.
    result: EagerResult = driver.execute_query(
        Query(cast(LiteralString, cypher), timeout=timeout_seconds),
        database_=database,
        routing_=RoutingControl.READ,
    )
    rows = [
        {
            key: coerce(value)
            for key, value in cast(Mapping[str, Any], record).items()
        }
        for record in result.records
    ]
    truncated = len(rows) > row_cap
    # Truncation is reported, never silent — the failure mode SPEC-001 names.
    return QueryResult(
        rows=rows[:row_cap], returned_rows=min(len(rows), row_cap), truncated=truncated
    )
