"""The single-document source protocol.

A manifest (CSV) becomes many documents; a document (PDF) becomes one. The two
are different operations, so they have different protocols — see the STORY-016
design. Extraction is partial by nature, so what it could not attribute travels
with the result rather than being dropped.
"""

from dataclasses import dataclass
from datetime import date

from policy_grapher.sources import SourceError


class DocumentSourceError(SourceError):
    """The file could not be read as a policy document."""


@dataclass(frozen=True)
class ExtractionReport:
    format: str
    section_found: bool
    attributed: tuple[str, ...]
    unattributed: tuple[str, ...]


@dataclass(frozen=True)
class ExtractedDocument:
    name: str
    references: tuple[str, ...]
    self_references_skipped: int
    report: ExtractionReport
    effective_date: date | None = None
