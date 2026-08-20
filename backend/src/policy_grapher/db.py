"""Neo4j driver lifecycle and schema."""

from neo4j import Driver, GraphDatabase, RoutingControl

from policy_grapher.config import Settings

CONSTRAINTS: tuple[str, ...] = (
    (
        "CREATE CONSTRAINT document_slug_unique IF NOT EXISTS "
        "FOR (d:Document) REQUIRE d.slug IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT document_name_unique IF NOT EXISTS "
        "FOR (d:Document) REQUIRE d.name IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT source_id_unique IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.id IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT document_version_id_unique IF NOT EXISTS "
        "FOR (v:DocumentVersion) REQUIRE v.version_id IS UNIQUE"
    ),
)


def create_driver(settings: Settings) -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def apply_constraints(driver: Driver, database: str) -> None:
    for statement in CONSTRAINTS:
        driver.execute_query(
            statement, database_=database, routing_=RoutingControl.WRITE
        )


def is_graph_empty(driver: Driver, database: str) -> bool:
    """Whether the graph holds no documents.

    Documents, not nodes: provenance (:Source) outlives what it described, so a
    create-then-delete round trip leaves an orphan :Source behind. Counting
    every node would make that invisible leftover read as content and stop
    startup auto-ingest (`main.maybe_autoingest`, the sole caller) from loading
    the sample corpus into what the user sees as an empty graph.
    """
    records, _, _ = driver.execute_query(
        "MATCH (d:Document) RETURN count(d) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["total"] == 0


def clear_graph(driver: Driver, database: str) -> tuple[int, int]:
    """Delete everything. Returns (nodes_deleted, relationships_deleted)."""
    _, summary, _ = driver.execute_query(
        "MATCH (n) DETACH DELETE n",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    return summary.counters.nodes_deleted, summary.counters.relationships_deleted
