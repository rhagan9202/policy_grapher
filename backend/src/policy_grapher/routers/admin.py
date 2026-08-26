from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver, RoutingControl
from pydantic import Field

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.db import clear_graph
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.export import export_graph
from policy_grapher.ingest import ingest_file
from policy_grapher.models import (
    DocumentIngestResult,
    IngestRequest,
    IngestResult,
    ResetResult,
    SourceFileOut,
)
from policy_grapher.sources import SourceError, list_sources, provenance
from policy_grapher.versions import VersionConflictError

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


# Only file-backed sources. `documents.py` merges a :Source with kind "api" and
# an empty filename for a document created through the API, and an empty string
# must never match a file on disk.
INGESTED_FILENAMES = """
MATCH (s:Source)
WHERE s.kind IN [$manifest, $document]
RETURN collect(s.filename) AS filenames
"""


@router.get("/ingest/sources", response_model=list[SourceFileOut])
def ingest_sources(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[SourceFileOut]:
    """What `POST /ingest` can be given, read out of the directory it reads from.

    The route takes a bare filename because the backend reads from its own
    container, so until this existed the screen was a free-text box over a
    directory only the server could see — know the name or guess it.

    One query for the whole listing rather than one per file: the flag is a set
    membership test, and a per-file round trip would make a directory of any
    size feel like a fault.
    """
    records, _, _ = driver.execute_query(
        INGESTED_FILENAMES,
        {"manifest": provenance.MANIFEST, "document": provenance.DOCUMENT},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    ingested = set(records[0]["filenames"]) if records else set()
    return [
        SourceFileOut(
            filename=source.filename,
            size_bytes=source.size_bytes,
            kind=source.kind,
            ingested=source.filename in ingested,
        )
        for source in list_sources(settings.data_dir)
    ]


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
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/export")
def export(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> dict[str, list[dict]]:
    """A copy of everything Reset deletes.

    No response_model: the categories are data, not a fixed schema, and pinning
    one here would mean editing two places every time the graph grows a label.
    `tests/test_export.py` asserts the categories and their identifiers instead.
    """
    return export_graph(driver, settings.neo4j_database)


@router.post("/reset", response_model=ResetResult)
def reset(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> ResetResult:
    nodes, relationships = clear_graph(driver, settings.neo4j_database)
    return ResetResult(nodes_deleted=nodes, relationships_deleted=relationships)
