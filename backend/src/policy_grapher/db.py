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
    (
        "CREATE CONSTRAINT authority_slug_unique IF NOT EXISTS "
        "FOR (a:Authority) REQUIRE a.slug IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT entity_slug_unique IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.slug IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE"
    ),
)

INDEXES: tuple[str, ...] = (
    # Exact designators ("DoDI 5000.88", "s.14(2)") are lexical. Embeddings are
    # poor at them, so the hybrid retrieval in phase 5 needs this leg.
    (
        "CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS "
        "FOR (c:Chunk) ON EACH [c.text]"
    ),
)


def create_driver(settings: Settings) -> Driver:
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def apply_schema(driver: Driver, database: str) -> None:
    for statement in (*CONSTRAINTS, *INDEXES):
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
