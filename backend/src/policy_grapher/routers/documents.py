from fastapi import APIRouter, Depends, HTTPException, Response
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.documents import (
    DocumentNotFoundError,
    NameConflictError,
    SelfReferenceError,
    add_reference,
    create_document,
    delete_document,
    get_document,
    list_documents,
    remove_reference,
)
from policy_grapher.models import ChunkOut, DocumentIn, DocumentOut, DocumentVersionOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found(slug: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No document with slug {slug!r}.")


@router.get("", response_model=list[DocumentOut])
def list_all(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DocumentOut]:
    return list_documents(driver, settings.neo4j_database)


@router.get("/{slug}", response_model=DocumentOut)
def read_one(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> DocumentOut:
    try:
        return get_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc


@router.post("", response_model=DocumentOut, status_code=201)
def create(
    body: DocumentIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> DocumentOut:
    try:
        return create_document(
            driver, settings.neo4j_database, body.name
        )
    except NameConflictError as exc:
        raise HTTPException(
            status_code=409, detail=f"A document named {body.name!r} already exists."
        ) from exc


@router.delete("/{slug}", status_code=204)
def delete(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        delete_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    return Response(status_code=204)


@router.post("/{slug}/references/{target_slug}", status_code=204)
def add_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        add_reference(driver, settings.neo4j_database, slug, target_slug)
    except SelfReferenceError as exc:
        raise HTTPException(
            status_code=400, detail="A document may not reference itself."
        ) from exc
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)


@router.delete("/{slug}/references/{target_slug}", status_code=204)
def remove_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> Response:
    try:
        remove_reference(driver, settings.neo4j_database, slug, target_slug)
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)


LIST_VERSIONS = """
MATCH (d:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion)
OPTIONAL MATCH (v)-[:SUPERSEDES]->(older:DocumentVersion)
RETURN v.version_id   AS version_id,
       v.effective_date AS effective_date,
       v.checksum     AS checksum,
       v.source_uri   AS source_uri,
       older.version_id AS supersedes
ORDER BY coalesce(v.effective_date, ''), v.ingested_at
"""


@router.get("/{slug}/versions", response_model=list[DocumentVersionOut])
def list_versions(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DocumentVersionOut]:
    records, _, _ = driver.execute_query(
        LIST_VERSIONS,
        {"slug": slug},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    return [DocumentVersionOut(**dict(record)) for record in records]


LIST_CHUNKS = """
MATCH (d:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion)
WHERE $version_id IS NULL OR v.version_id = $version_id
WITH v ORDER BY coalesce(v.effective_date, '') DESC, v.ingested_at DESC
LIMIT 1
MATCH (v)-[:HAS_CHUNK]->(c:Chunk)
RETURN c.chunk_id     AS chunk_id,
       c.text         AS text,
       c.page         AS page,
       c.section_path AS section_path,
       c.ordinal      AS ordinal
ORDER BY c.ordinal
"""


@router.get("/{slug}/chunks", response_model=list[ChunkOut])
def list_chunks(
    slug: str,
    version_id: str | None = None,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[ChunkOut]:
    """A version's chunks, ordered by `ordinal`.

    `version_id` picks one edition explicitly; omitted, it resolves to the
    newest version by the same "latest labelled date, then latest ingest"
    ordering `link_supersession` uses to build the SUPERSEDES chain — see
    `versions.link_supersession`.
    """
    records, _, _ = driver.execute_query(
        LIST_CHUNKS,
        {"slug": slug, "version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    return [ChunkOut(**dict(record)) for record in records]
