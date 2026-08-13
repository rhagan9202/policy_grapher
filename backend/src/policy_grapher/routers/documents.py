from fastapi import APIRouter, Depends, HTTPException, Response
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.documents import (
    DocumentNotFoundError,
    ExternalDocumentError,
    NameConflictError,
    NameMismatchError,
    create_document,
    delete_document,
    get_document,
    list_documents,
    update_document,
)
from policy_grapher.models import DocumentIn, DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found(slug: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No document with slug {slug!r}.")


@router.get("", response_model=list[DocumentOut])
def list_all(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> list[DocumentOut]:
    return list_documents(driver, settings.neo4j_database)


@router.get("/{slug}", response_model=DocumentOut)
def read_one(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
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
) -> DocumentOut:
    try:
        return create_document(
            driver, settings.neo4j_database, body.name, body.reference_role
        )
    except NameConflictError as exc:
        raise HTTPException(
            status_code=409, detail=f"A document named {body.name!r} already exists."
        ) from exc


@router.put("/{slug}", response_model=DocumentOut)
def update(
    slug: str,
    body: DocumentIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> DocumentOut:
    try:
        return update_document(
            driver, settings.neo4j_database, slug, body.name, body.reference_role
        )
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    except ExternalDocumentError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{slug!r} is an external document and has no reference_role.",
        ) from exc
    except NameMismatchError as exc:
        raise HTTPException(
            status_code=400,
            detail="Body name does not match the addressed document; renaming means delete and recreate.",
        ) from exc


@router.delete("/{slug}", status_code=204)
def delete(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    try:
        delete_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    return Response(status_code=204)
