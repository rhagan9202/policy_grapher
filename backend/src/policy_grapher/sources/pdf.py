"""Extract a DoD issuance PDF into a document and its cited references.

Five stages, each a pure function: detect the format, locate the references
section, split it into entries, take each entry's identifier, normalise the
identifier to the vocabulary the corpus uses. Stage 2 is where extraction
fails catastrophically when it fails at all, so it reports "not found"
explicitly rather than returning an empty string.
"""

import re
from pathlib import Path

from pypdf import PdfReader


def text_of(path: Path) -> str:
    """Every page's text, joined by newlines."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


# The heading is spelled three ways across the sample fixtures: a bare REFERENCES,
# "ENCLOSURE 1" then REFERENCES, and an unnumbered "ENCLOSURE" then REFERENCES.
# Entry markers were consistent where headings were not, so detection keys on them.
_HEADING = re.compile(r"(?:ENCLOSURE(?:\s+\d+)?\s*\n+\s*)?REFERENCES\s*\n", re.IGNORECASE)
_LETTERED = re.compile(r"\(\s*[a-z]{1,3}\s*\)\s+")
_SECTION_END = re.compile(r"\n\s*(?:ENCLOSURE\s+\d+|GLOSSARY|APPENDIX)\s*\n", re.IGNORECASE)
# A modern section lists citations directly; a body mention does not. The opening
# entry isn't always a DoD issuance itself (e.g. an NDS summary), so this looks a
# little way into the section rather than requiring a match at the very start.
_MODERN_MARKER = re.compile(
    r"(?:DoD (?:Directive|Instruction|Manual)|Public Law|Chairman of the Joint Chiefs of Staff)\s"
)


# Modern sections have no per-entry marker, so entries are cut where a new citation
# begins. A citation always starts at the beginning of a source line — continuation
# lines wrap without repeating an opener — so the boundary is anchored to line starts
# and matched against the *un-flattened* section text. Matching after flattening (as
# a first draft of this did) lets an opener phrase that merely appears mid-entry (e.g.
# "Under Secretary" inside a DoD Directive's own title, or "Secretary of" inside that)
# trigger a spurious split, shredding the entry. This list is deliberately broader than
# _MODERN_MARKER above: that one only needs one confident hit to identify the format,
# so it stays narrow to avoid false-positiving on a body paragraph; this one has to
# recognise every entry's opener or the split silently swallows it into its neighbour.
# Widening _MODERN_MARKER to match would trade its precision for this one's recall, so
# the two are kept separate rather than merged.
_MODERN_BOUNDARY = re.compile(
    r"^(?=(?:DoD |Public Law |Military[ -]Standard |Executive Order |United States Code|"
    r"Title \d|Section \d|Chairman |Under Secretary |Deputy Secretary |Secretary of |"
    r"Assistant Secretary |Director |Federal |National |Department of |Joint |"
    r"Office of |Committee |Code of Federal|Administrative |Directive-[Tt]ype |"
    r"Intelligence |International |Defense ))",
    re.MULTILINE,
)


def split_entries(fmt: str, section: str) -> list[str]:
    """One string per citation, with the source's line wrapping undone."""
    if fmt == "legacy":
        flat = re.sub(r"\s*\n\s*", " ", section).strip()
        parts = _LETTERED.split(flat)
        # split() yields [before-first-marker, entry, entry, ...]
        return [part.strip() for part in parts[1:] if part.strip()]
    # Split on the raw section first so the boundary can key on line starts, then
    # flatten each entry's own internal wrapping.
    raw_parts = [part for part in _MODERN_BOUNDARY.split(section) if part.strip()]
    return [re.sub(r"\s*\n\s*", " ", part).strip() for part in raw_parts]


def locate_references(full: str) -> tuple[str, str | None]:
    """Find the references section and say which format it is.

    Returns ("unknown", None) when no section is found — distinct from an empty
    section, which would look identical downstream and mean something different.
    """
    for match in _HEADING.finditer(full):
        body = full[match.end() :]
        end = _SECTION_END.search(body)
        section = body[: end.start()] if end else body
        if not section.strip():
            continue
        if _HEADING.search(section):
            # The boundary swallowed another REFERENCES-shaped line (e.g. a
            # dot-leader-free table-of-contents entry that happens to match the
            # heading pattern). That means this candidate's slice ran past the
            # real section instead of stopping at it, so it isn't trustworthy —
            # skip it and let the next, cleanly-bounded candidate be evaluated.
            continue
        if _LETTERED.match(section.lstrip()):
            return "legacy", section
        if _MODERN_MARKER.search(section[:600]):
            return "modern", section
    return "unknown", None
