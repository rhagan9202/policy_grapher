import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from policy_grapher.config import Settings, get_settings
from policy_grapher.db import apply_schema, create_driver, is_graph_empty
from policy_grapher.embedding import build_embedder
from policy_grapher.extraction import build_extractor
from policy_grapher.ingest import ingest_file
from policy_grapher.jobs.queue import build_queue
from policy_grapher.migrate import migrate_pairing_decisions
from policy_grapher.models import IngestResult
from policy_grapher.routers import (
    admin,
    ask,
    documents,
    graph,
    pairings,
    rebuilds,
    review,
    triage,
)
from policy_grapher.sources import SourceError

logger = logging.getLogger(__name__)


def maybe_autoingest(driver, settings: Settings) -> IngestResult | None:
    """Load the sample corpus if configured to and the graph is empty.

    Runs at startup only, called once from `lifespan`. This is not a
    reaction to emptiness: a graph emptied later (e.g. by a future
    POST /reset) stays empty until the process restarts, because nothing
    re-invokes this check.
    """
    if not settings.auto_ingest:
        return None
    if not is_graph_empty(driver, settings.neo4j_database):
        return None

    try:
        result = ingest_file(
            driver, settings.neo4j_database, settings.sample_csv, settings.data_dir
        )
    except SourceError as exc:
        # A missing or malformed sample must not stop the API from serving.
        logger.warning("Auto-ingest skipped: %s", exc)
        return None

    logger.info(
        "Auto-ingested %s: %d nodes, %d relationships",
        settings.sample_csv,
        result.nodes_created,
        result.relationships_created,
    )
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    driver = create_driver(settings)
    driver.verify_connectivity()
    apply_schema(driver, settings.neo4j_database)
    # After apply_schema on purpose: the migration MERGEs on
    # :PairingDecision.key and needs pairing_decision_key_unique in place
    # before its first write. Idempotent, so every boot runs it; only a boot
    # that finds legacy same-document decisions or proposals does any work.
    migrated = migrate_pairing_decisions(driver, settings.neo4j_database)
    logger.info("Pairing decision migration: %s", migrated)
    # Its own record, and the argument is that a number nobody reads is the same
    # as not reporting it. The other counters report work done, and a zero among
    # them is ordinary. This one means a decision node carried a verdict
    # `record_decision` could not have written — corruption, worth investigating
    # — and it is announced exactly once, because the node is retired and the
    # next boot reports zero. One line among nine counters is not an
    # announcement of that.
    corrupt = migrated["retired_unknown_verdict"]
    if corrupt:
        logger.warning(
            "Pairing decision migration: %d link decision(s) carried a verdict "
            "no vocabulary recognises and were retired unconverted. "
            "`record_decision` has always refused any value outside its own "
            "verdicts, so a node holding one was written around it. The verdict "
            "survives under :RetiredLinkDecision with retired_reason "
            "'unknown_verdict' and is in the export; this is the only boot that "
            "will report it.",
            corrupt,
        )
    # Its own record too, and for a different reason from the one above: this is
    # a census rather than a repair, so unlike the counters that go quiet once
    # the work is done it prints on every boot for as long as the condition
    # lasts. Inside the INFO dict that makes it indistinguishable from noise — a
    # line the reader learns to skip. The sentence is here rather than only in
    # the docstring because an operator is standing in a log, not in the source.
    unreadable = migrated["decisions_missing_documents"]
    if unreadable:
        logger.warning(
            "Pairing decision migration: %d link decision(s) could not be "
            "classified, because their obligations no longer resolve to a "
            "document. Nothing was changed for them, so the graph may still "
            "hold same-document IMPLEMENTS edges this migration could not "
            "reach. Repairing that means document deletion cascading to its "
            "obligations, which is a separate concern.",
            unreadable,
        )
    # Built here for its side effect of validating the configuration: an unknown
    # EXTRACTOR_ADAPTER raises, and boot is where that is cheap to notice. Nothing
    # drives extraction yet — phase 4's rebuild is the caller — so the instance is
    # held on app.state rather than used, and the null default touches no network.
    extractor = build_extractor(settings)
    # Same reason, and just as cheap: build_embedder only resolves the name.
    # LocalEmbedder loads its model lazily on first use, so a "local" setting
    # does not pay nine seconds of torch import here.
    embedder = build_embedder(settings)
    # Lazy: Redis being down must not stop the app booting, since every route
    # but the two rebuild ones talks to Neo4j.
    queue = build_queue(settings)
    maybe_autoingest(driver, settings)

    app.state.driver = driver
    app.state.settings = settings
    app.state.extractor = extractor
    app.state.embedder = embedder
    app.state.queue = queue
    try:
        yield
    finally:
        driver.close()


# The app is constructed at import time, but app.state.settings is only populated
# inside lifespan, which runs later — read settings via get_settings() here instead.
settings = get_settings()

# FastAPI attaches no dependencies to its own documentation routes, so with them
# published "every route but /health requires a bearer token" would be false:
# /openapi.json hands an anonymous caller the whole route inventory. Passing
# openapi_url=None removes all three (/docs and /redoc are only registered when the
# schema is). ENABLE_API_DOCS puts them back for a deployment that wants them.
_docs = settings.enable_api_docs
app = FastAPI(
    title="Policy Grapher",
    version="0.1.0",
    lifespan=lifespan,
    openapi_url="/openapi.json" if _docs else None,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
)

_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # False on purpose: the credential is an Authorization header the dev proxy adds
    # server-side, never a cookie, so allow_credentials buys nothing — and it is what
    # would turn a future CORS_ALLOW_ORIGINS=* into "any origin, with credentials".
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(ask.router)
app.include_router(documents.router)
app.include_router(graph.router)
app.include_router(pairings.router)
app.include_router(rebuilds.router)
app.include_router(review.router)
app.include_router(triage.router)
