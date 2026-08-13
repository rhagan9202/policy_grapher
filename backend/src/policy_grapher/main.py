import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from policy_grapher.config import Settings, get_settings
from policy_grapher.csv_source import CsvSourceError
from policy_grapher.db import apply_constraints, create_driver, is_graph_empty
from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.ingest import ingest_file
from policy_grapher.models import GraphOut, IngestRequest, IngestResult

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
    except CsvSourceError as exc:
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


app = FastAPI(title="Policy Grapher", version="0.1.0", lifespan=lifespan)

# DI-1 is local-only and unauthenticated. See SPEC-001 (CORS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResult)
def ingest(request: IngestRequest) -> IngestResult:
    settings: Settings = app.state.settings
    try:
        return ingest_file(
            app.state.driver,
            settings.neo4j_database,
            request.filename,
            settings.data_dir,
        )
    except CsvSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/graph", response_model=GraphOut)
def graph(
    include_external: bool = False,
    expand: str | None = None,
    limit: int | None = Query(default=None, ge=0),
) -> GraphOut:
    settings: Settings = app.state.settings
    effective_limit = settings.graph_render_cap if limit is None else limit
    try:
        return build_graph(
            app.state.driver,
            settings.neo4j_database,
            include_external=include_external,
            expand=expand,
            limit=effective_limit,
        )
    except UnknownDocumentError as exc:
        raise HTTPException(
            status_code=404, detail=f"No document with slug {exc.args[0]!r}."
        ) from exc
