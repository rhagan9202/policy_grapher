from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.documents import (
    DocumentNotFoundError,
    get_document,
    list_documents,
)
from policy_grapher.models import DocumentOut

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
