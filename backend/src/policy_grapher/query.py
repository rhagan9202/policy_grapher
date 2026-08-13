"""Raw Cypher passthrough.

Unrestricted by decision — no read-only enforcement, no timeout, no row cap.
See ADR-004; that acceptance is bounded by DI-1 staying local-only.
"""

from neo4j import Driver, RoutingControl
from neo4j.graph import Node, Path, Relationship

JSON_SCALARS = (str, int, float, bool)


def coerce(value: object) -> object:
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


def run_cypher(driver: Driver, database: str, cypher: str) -> list[dict]:
    # WRITE routing: ADR-004 permits mutation through this endpoint.
    records, _, _ = driver.execute_query(
        cypher, database_=database, routing_=RoutingControl.WRITE
    )
    return [{key: coerce(value) for key, value in record.items()} for record in records]
