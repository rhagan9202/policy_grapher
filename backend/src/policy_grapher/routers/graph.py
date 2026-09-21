from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import Neo4jError

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.models import GraphOut, QueryRequest, QueryResult
from policy_grapher.query import run_cypher

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=GraphOut)
def graph(
    # Tri-state on purpose: the focused mode answers a different question and
    # cannot honour this flag, so it has to refuse a caller who set it. A plain
    # `bool = False` cannot tell "sent false" from "never sent", which would
    # make the refusal below fire on every focused request.
    include_external: bool | None = None,
    expand: str | None = None,
    limit: int | None = Query(default=None, ge=0),
    focus: str | None = None,
    depth: int = Query(default=1, ge=1, le=3),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> GraphOut:
    # `focus` and `expand` answer different questions — one document's
    # neighbourhood, versus the corpus with one document's externals added — and
    # the focused mode reads neither `expand` nor `include_external`. Answering
    # 200 while silently dropping a parameter the caller sent is worse than
    # refusing: it looks like the narrower answer was the one they asked for.
    if focus is not None and (expand is not None or include_external is not None):
        raise HTTPException(
            status_code=422,
            detail=(
                "focus is mutually exclusive with expand and include_external: "
                "focus returns one document's neighbourhood, which admits no "
                "document from outside it. Send focus alone, or send expand "
                "and include_external without it."
            ),
        )
    # Bounded at three rather than left open: each degree is another round trip
    # and another multiplication of the node set, and a reader who wanted the
    # whole corpus asked the wrong question — that is what the corpus-wide mode
    # is for.
    effective_limit = settings.graph_render_cap if limit is None else limit
    try:
        return build_graph(
            driver,
            settings.neo4j_database,
            include_external=bool(include_external),
            expand=expand,
            limit=effective_limit,
            focus=focus,
            depth=depth,
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
    principal: Principal = Depends(require_principal),
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
