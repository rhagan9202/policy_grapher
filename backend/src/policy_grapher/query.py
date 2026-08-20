"""Read-only Cypher passthrough.

Read routing, a transaction timeout and a row cap, per ADR-009. Mutation moved to
authenticated routes when ADR-004's local-only assumption stopped holding.
"""

from typing import LiteralString, cast

from neo4j import READ_ACCESS, Driver, Query
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
    """Run one caller-supplied query, reading at most `row_cap` rows out of it.

    The rows are pulled one at a time rather than through `driver.execute_query`,
    which returns an `EagerResult`: that materialised and coerced every record before
    the cap could be applied, so `UNWIND range(1, 1000000000) AS i RETURN i` built
    millions of dicts in this process for the whole timeout window. Here the loop
    stops one row past the cap and the session closes with the rest of the result
    unconsumed, so `truncated` is observed rather than derived from a full count.

    A cap of `0` means no cap, matching `GRAPH_RENDER_CAP` (SPEC-001, *Render cap*).
    That is deliberate large-result testing, and it gives up the bound above.
    """
    cap = None if row_cap == 0 else row_cap
    rows: list[dict[str, JSONValue]] = []
    truncated = False

    # READ access mode: Neo4j rejects a write attempted in a read transaction, so the
    # enforcement is the database's, not a regex over the query text.
    with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
        query = Query(cast(LiteralString, cypher), timeout=timeout_seconds)
        result = session.run(query)
        for record in result:
            if cap is not None and len(rows) == cap:
                # One row past the cap: proof there was more, without reading more.
                truncated = True
                break
            rows.append({key: coerce(value) for key, value in record.items()})

    # Truncation is reported, never silent — the failure mode SPEC-001 names.
    return QueryResult(rows=rows, returned_rows=len(rows), truncated=truncated)
