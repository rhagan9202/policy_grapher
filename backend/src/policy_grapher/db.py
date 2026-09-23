"""Neo4j driver lifecycle and schema."""

from neo4j import (
    Driver,
    GraphDatabase,
    NotificationClassification,
    RoutingControl,
)
from neo4j.exceptions import AuthError

from policy_grapher.config import Settings

# Why a rejected password gets a paragraph instead of a one-line raise.
#
# `NEO4J_AUTH` is read only when Neo4j initialises an *empty* data directory.
# Once `/data/dbms/auth.ini` exists the stored credential wins and the variable
# is ignored on every later start — silently, with nothing in Neo4j's own log
# saying it was disregarded. A `.env` regenerated after a first `up`, or an `up`
# that ran before `scripts/init-env.sh` wrote one, therefore leaves the stack
# handing Neo4j a password the database has never held.
#
# Every signal an operator would reach for says the configuration is right:
# `docker compose config` renders the new password, `.env` holds it, and the
# neo4j container reports *healthy* because its healthcheck is HTTP-only —
# deliberately, since a cypher-shell check would need credentials nothing
# provides and would block `backend` for ever (docker-compose.yml:16-19). The
# only component that disagrees is the one that authenticates, and the driver's
# own message sends the reader to look at the password, which is the one thing
# that is not wrong.
AUTH_REFUSED_HINT = """Neo4j rejected the configured credentials.

The usual cause is a database volume that outlived the .env that created it.
NEO4J_AUTH is read only when Neo4j initialises an empty data directory; once
/data/dbms/auth.ini exists, the stored password wins and NEO4J_AUTH is ignored
on every later start. So a regenerated .env -- or an `up` that ran before
scripts/init-env.sh wrote one -- leaves the stack handing Neo4j a password the
database has never held, while `docker compose config` still shows the new one
and the neo4j container still reports healthy (its healthcheck is HTTP-only, by
design).

Confirm it by comparing when each was written:

    docker run --rm -v "$(basename $PWD)_neo4j-data:/data" alpine \\
        stat -c '%y  %n' /data/dbms/auth.ini
    stat -c '%y  %n' .env

An auth.ini older than .env is this failure.

If the graph is disposable:

    docker compose down -v && docker compose up --build

That deletes the graph, reviewed verdicts included -- export first if it holds
anything nothing can regenerate. Otherwise restore the NEO4J_PASSWORD and
NEO4J_AUTH that initialised the volume; the stored password is hashed and
cannot be read back out.

.env and the neo4j-data volume are a matched pair: replace either and you must
replace both."""


class Neo4jAuthenticationRefused(RuntimeError):
    """Neo4j refused the configured credentials at startup.

    Carries `AUTH_REFUSED_HINT` rather than the driver's own message because the
    driver's is accurate and useless: it reports that authentication failed,
    which the operator already knows, and says nothing about the one mechanism
    that makes a correct-looking configuration fail.
    """


def verify_credentials(driver: Driver) -> None:
    """Open a connection now, so a bad password fails at boot with an explanation.

    `create_driver` connects lazily, so without this the first symptom is
    whichever query happens to run first -- `apply_schema` at startup, or a
    rebuild job minutes into a run -- failing far from its cause.
    """
    try:
        driver.verify_connectivity()
    except AuthError as cause:
        raise Neo4jAuthenticationRefused(AUTH_REFUSED_HINT) from cause

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
    # :PairingDecision is the same kind of thing for the other question — a
    # same-document pairing verdict, canonical for the same ADR-014 reason.
    # Uniqueness on the directional key is what lets a re-verdict update in
    # place, and the repoint path's collision screening assumes it.
    (
        "CREATE CONSTRAINT pairing_decision_key_unique IF NOT EXISTS "
        "FOR (d:PairingDecision) REQUIRE d.key IS UNIQUE"
    ),
    # :PairingLock is the write lock serialising verdicts within one edition
    # pair, and this constraint is half of the mechanism rather than hygiene
    # around it. `links.pairing.ACQUIRE_PAIR_LOCK` is a bare MERGE, and a MERGE
    # racing itself creates a second node for the same key unless a uniqueness
    # constraint makes it lock the index entry first — two transactions then
    # lock two different nodes, block on neither, and the two-live-paired race
    # this lock exists to close is open again with the lock in place.
    (
        "CREATE CONSTRAINT pairing_lock_key_unique IF NOT EXISTS "
        "FOR (lock:PairingLock) REQUIRE lock.key IS UNIQUE"
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
