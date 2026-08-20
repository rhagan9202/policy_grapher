from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver
from pydantic import Field

from policy_grapher.auth import Principal, require_principal
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
from policy_grapher.sources import SourceError

# Tagged explicitly rather than left to smart-union matching: the two models are
# already mutually exclusive on their `source` Literal, but a discriminator makes
# that the contract instead of a consequence, and keeps it true if a future field
# change would otherwise reopen a coercion path.
IngestResponse = Annotated[
    IngestResult | DocumentIngestResult, Field(discriminator="source")
]

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    body: IngestRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> IngestResult | DocumentIngestResult:
    try:
        return ingest_file(
            driver, settings.neo4j_database, body.filename, settings.data_dir
        )
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reset", response_model=ResetResult)
def reset(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> ResetResult:
    nodes, relationships = clear_graph(driver, settings.neo4j_database)
    return ResetResult(nodes_deleted=nodes, relationships_deleted=relationships)
