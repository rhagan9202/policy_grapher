import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from policy_grapher.config import Settings, get_settings
from policy_grapher.db import apply_constraints, create_driver, is_graph_empty
from policy_grapher.ingest import ingest_file
from policy_grapher.models import IngestResult
from policy_grapher.routers import admin, documents, graph
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
    apply_constraints(driver, settings.neo4j_database)
    maybe_autoingest(driver, settings)

    app.state.driver = driver
    app.state.settings = settings
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
app.include_router(documents.router)
app.include_router(graph.router)
