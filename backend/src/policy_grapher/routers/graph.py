from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import Neo4jError

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.models import GraphOut, QueryRequest, QueryResult
from policy_grapher.query import run_cypher

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=GraphOut)
def graph(
    include_external: bool = False,
    expand: str | None = None,
    limit: int | None = Query(default=None, ge=0),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> GraphOut:
    effective_limit = settings.graph_render_cap if limit is None else limit
    try:
        return build_graph(
            driver,
            settings.neo4j_database,
            include_external=include_external,
            expand=expand,
            limit=effective_limit,
        )
    except UnknownDocumentError as exc:
        raise HTTPException(
            status_code=404, detail=f"No document with slug {exc.args[0]!r}."
        ) from exc


@router.post("/query", response_model=QueryResult)
def query(
    body: QueryRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> QueryResult:
    try:
        return run_cypher(
            driver,
            settings.neo4j_database,
            body.cypher,
            row_cap=settings.query_row_cap,
            timeout_seconds=settings.query_timeout_seconds,
        )
    except Neo4jError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
