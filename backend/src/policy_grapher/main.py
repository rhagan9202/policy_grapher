from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from policy_grapher.config import Settings, get_settings
from policy_grapher.csv_source import CsvSourceError
from policy_grapher.db import apply_constraints, create_driver
from policy_grapher.ingest import ingest_file
from policy_grapher.models import IngestRequest, IngestResult


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    driver = create_driver(settings)
    driver.verify_connectivity()
    apply_constraints(driver, settings.neo4j_database)

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
