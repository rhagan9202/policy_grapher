from fastapi import APIRouter, Depends, HTTPException, Response
from neo4j import Driver

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
from policy_grapher.models import DocumentIn, DocumentOut

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
