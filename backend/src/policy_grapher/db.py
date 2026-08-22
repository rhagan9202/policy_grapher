"""Neo4j driver lifecycle and schema."""

from neo4j import (
    Driver,
    GraphDatabase,
    NotificationClassification,
    RoutingControl,
)

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
    (
        "CREATE CONSTRAINT obligation_id_unique IF NOT EXISTS "
        "FOR (o:Obligation) REQUIRE o.obligation_id IS UNIQUE"
    ),
    # The cache is MERGEd on `key` on every extraction. Without uniqueness a
    # concurrent ingest can create a second node under the same key, and the
    # reader then picks one of two rows arbitrarily — a cache that is sometimes
    # right is worse than no cache.
    (
        "CREATE CONSTRAINT extraction_cache_key_unique IF NOT EXISTS "
        "FOR (e:ExtractionCache) REQUIRE e.key IS UNIQUE"
    ),
    # :LinkDecision is canonical, not derived — it records what a human decided
    # and no rebuild may drop it. Uniqueness on the content-derived key is what
    # lets a re-decision update a verdict in place instead of accumulating a
    # second, contradictory record beside the first.
    (
        "CREATE CONSTRAINT link_decision_key_unique IF NOT EXISTS "
        "FOR (d:LinkDecision) REQUIRE d.key IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT change_id_unique IF NOT EXISTS "
        "FOR (c:Change) REQUIRE c.change_id IS UNIQUE"
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
    """The driver every caller shares.

    `UNRECOGNIZED` notifications are switched off, and the reason is a property of
    Neo4j rather than of this code: **setting a property to null deletes it**, so
    an optional field that has never once been non-null in a database has no
    property key at all — and every query naming one is answered with an `01N52`
    warning carrying the whole query text inline.

    This data model is full of such fields, and several are legitimately unwritten
    for as long as a feature is unused: `Change.previous_statement` exists only for
    a MODIFIED change (STORY-047 records why a reissue produces none),
    `Chunk.embedding` only once a real embedder runs, and an obligation's
    `deadline` and `conditions` only when the extractor finds them. None of those
    is a typo, and none clears on its own, so the warnings are unactionable noise
    that grows with every optional field added.

    What this gives up is that the same class catches a genuinely misspelled
    property — and that is covered better elsewhere. A typo returns null, and the
    integration suites assert real values against real containers, so it fails a
    test instead of being logged where nobody greps. `tests/test_db.py` pins this
    configuration so it cannot be quietly undone.
    """
    return GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        notifications_disabled_classifications=[
            NotificationClassification.UNRECOGNIZED
        ],
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
