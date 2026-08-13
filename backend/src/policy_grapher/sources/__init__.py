"""Ingestion sources. A manifest becomes many documents; a document becomes one."""

from pathlib import Path

DOCUMENT_SUFFIXES = {".pdf"}


def is_document_source(path: Path) -> bool:
    """True when the file is a single policy document rather than a manifest."""
    return path.suffix.lower() in DOCUMENT_SUFFIXES
