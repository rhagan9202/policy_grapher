"""Ingestion sources. A manifest becomes many documents; a document becomes one.

Both kinds arrive the same way — a bare filename resolved under the data directory —
so the resolver and the error both live here rather than in either branch. They used
to sit in the CSV reader, which meant a missing PDF raised a CSV-flavoured error.
"""

from pathlib import Path

DOCUMENT_SUFFIXES = {".pdf"}


class SourceError(ValueError):
    """A source file could not be located or could not be read as expected."""


def is_document_source(path: Path) -> bool:
    """True when the file is a single policy document rather than a manifest."""
    return path.suffix.lower() in DOCUMENT_SUFFIXES


def resolve_source_path(filename: str, data_dir: Path) -> Path:
    """Resolve a bare filename under data_dir, refusing anything that escapes it."""
    if not filename or Path(filename).name != filename:
        raise SourceError(f"{filename!r} is not a bare filename; give a name, not a path.")

    root = data_dir.resolve()
    path = (root / filename).resolve()
    if not path.is_relative_to(root):
        raise SourceError(f"{filename!r} resolves outside the data directory.")
    if not path.is_file():
        raise SourceError(f"{filename!r} was not found in the data directory.")
    return path
