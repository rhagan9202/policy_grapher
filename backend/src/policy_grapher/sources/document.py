"""The single-document source protocol.

A manifest (CSV) becomes many documents; a document (PDF) becomes one. The two
are different operations, so they have different protocols — see the STORY-016
design. Extraction is partial by nature, so what it could not attribute travels
with the result rather than being dropped.
"""

from dataclasses import dataclass, field
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
    # Page text, in reading order — what phase 2 chunks against. Defaulted to an
    # empty list, not required, because most existing constructions of this
    # dataclass (hand-built fixtures for slug/version tests) care about identity
    # or dates, not text, and chunking an empty page list is a safe, silent no-op
    # rather than a forced field every unrelated test would have to fill in.
    pages: list[str] = field(default_factory=list)
