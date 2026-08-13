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


_QUOTED_TITLE = re.compile(r"(.+?),\s*[“\"]")
# Entries that carry no quoted title at all, e.g. "Title 10, United States Code" (the
# order legacy documents use) or "United States Code, Title 10" (the order modern
# documents use — and already the corpus's target vocabulary, see normalise() below).
_CODE_CITATION = re.compile(
    r"((?:Title|Section)\s+[\dA-Za-z().]+,\s*United States Code"
    r"|United States Code,\s*Title\s+\d+)"
)
_ISSUANCE = re.compile(r"^DoD\s+(Directive|Instruction|Manual)\s+([0-9][0-9.\-]*[A-Z]?)$", re.IGNORECASE)
# Only matches the legacy "Title N, United States Code" order. An identifier already
# in the reversed "United States Code, Title N" order — the corpus's target vocabulary
# — falls through unmatched, so normalise() leaves it as-is instead of reversing it
# a second time.
_US_CODE = re.compile(r"^Title\s+(\d+),\s*United States Code$", re.IGNORECASE)
_ABBREVIATION = {"directive": "DoDD", "instruction": "DoDI", "manual": "DoDM"}

# Longer than any real identifier in the sample corpus; a longer match means the
# entry boundary was wrong, and a wrong name is worse than an unattributed one.
_MAX_IDENTIFIER = 140


def identifier(entry: str) -> str | None:
    """The citation's leading identifier, or None if the entry has none."""
    match = _QUOTED_TITLE.match(entry)
    if match:
        name = match.group(1)
    else:
        code = _CODE_CITATION.match(entry)
        if not code:
            return None
        name = code.group(1)
    name = name.strip().rstrip(",").strip()
    if not name or len(name) > _MAX_IDENTIFIER:
        return None
    return name


# Modern cover page: "DOD DIRECTIVE 5000.01" on one line.
_MODERN_HEADER = re.compile(
    r"DOD\s+(DIRECTIVE|INSTRUCTION|MANUAL)\s+([0-9][0-9.\-]*[A-Z]?)", re.IGNORECASE
)
# Legacy cover page: "DIRECTIVE" ... "NUMBER 5143.01", separated by blank lines.
_LEGACY_HEADER = re.compile(
    r"\b(DIRECTIVE|INSTRUCTION|MANUAL)\b\s*\n[\s\S]{0,200}?NUMBER\s+([0-9][0-9.\-]*[A-Z]?)",
    re.IGNORECASE,
)
# Both header patterns are shaped just like a body citation to another issuance (a
# references-section entry, or a "Reissues DoD Directive ..." mention), and searching
# the whole document lets one of those win instead of the cover page — e.g. DoDI
# 8500.01's own references section opens "(a) DoD Directive 8500.01, ...", a *cited*,
# cancelled predecessor that the unbounded modern pattern matches before ever reaching
# the true "Department of Defense / INSTRUCTION / NUMBER 8500.01" cover page, producing
# the wrong type (DoDD instead of DoDI) for the right number. Every sample fixture's
# real header match starts within the first 40 characters, and the earliest thing that
# could be mistaken for one (a references heading or citation) starts at character
# 10,529 — so bounding the search to a generous prefix keeps the cover page's match the
# only one the patterns can find, without needing to locate the references section first.
_COVER_PAGE_SPAN = 2000


def document_name(full: str) -> str | None:
    """The issuance's own name, in the corpus's vocabulary."""
    cover = full[:_COVER_PAGE_SPAN]
    for pattern in (_MODERN_HEADER, _LEGACY_HEADER):
        match = pattern.search(cover)
        if match:
            kind = _ABBREVIATION[match.group(1).lower()]
            return f"{kind} {match.group(2)}"
    return None


def normalise(name: str) -> str:
    """Map an identifier to the vocabulary the corpus CSV uses."""
    code = _US_CODE.match(name)
    if code:
        return f"United States Code, Title {code.group(1)}"
    issuance = _ISSUANCE.match(name)
    if issuance:
        return f"{_ABBREVIATION[issuance.group(1).lower()]} {issuance.group(2)}"
    return name
