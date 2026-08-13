from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.db import clear_graph
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.ingest import ingest_file
from policy_grapher.models import (
    DocumentIngestResult,
    IngestRequest,
    IngestResult,
    ResetResult,
)
from policy_grapher.sources.document import DocumentSourceError
from policy_grapher.sources.manifest import CsvSourceError

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingest", response_model=IngestResult | DocumentIngestResult)
def ingest(
    body: IngestRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> IngestResult | DocumentIngestResult:
    try:
        return ingest_file(
            driver, settings.neo4j_database, body.filename, settings.data_dir
        )
    except (CsvSourceError, DocumentSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset", response_model=ResetResult)
def reset(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> ResetResult:
    nodes, relationships = clear_graph(driver, settings.neo4j_database)
    return ResetResult(nodes_deleted=nodes, relationships_deleted=relationships)
