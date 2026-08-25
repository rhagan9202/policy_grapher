"""Ingestion sources. A manifest becomes many documents; a document becomes one.

Both kinds arrive the same way — a bare filename resolved under the data directory —
so the resolver and the error both live here rather than in either branch. They used
to sit in the CSV reader, which meant a missing PDF raised a CSV-flavoured error.
"""

from dataclasses import dataclass
from pathlib import Path

from policy_grapher.sources import provenance

DOCUMENT_SUFFIXES = {".pdf"}


class SourceError(ValueError):
    """A source file could not be located or could not be read as expected."""


def is_document_source(path: Path) -> bool:
    """True when the file is a single policy document rather than a manifest."""
    return path.suffix.lower() in DOCUMENT_SUFFIXES


@dataclass(frozen=True)
class SourceFile:
    """A file the backend can ingest, and what ingest would make of it."""

    filename: str
    size_bytes: int
    kind: str


def list_sources(data_dir: Path) -> list[SourceFile]:
    """Every file in `data_dir`, by name.

    `kind` is read off `is_document_source` — the same predicate `ingest_file`
    branches on — rather than off a second rule that happens to agree today. A
    listing that labels a file one way while ingest treats it another is worse
    than no listing: it is confidently wrong rather than merely unhelpful.

    Sorted, because a directory in filesystem order reads differently on every
    machine. Non-recursive and files only, matching what `resolve_source_path`
    will accept: offering a name that ingest would then refuse is the same
    defect from the other end.
    """
    root = data_dir.resolve()
    if not root.is_dir():
        return []
    return sorted(
        (
            SourceFile(
                filename=path.name,
                size_bytes=path.stat().st_size,
                kind=provenance.DOCUMENT if is_document_source(path) else provenance.MANIFEST,
            )
            for path in root.iterdir()
            if path.is_file()
        ),
        key=lambda source: source.filename,
    )


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
