"""Extract a DoD issuance PDF into a document and its cited references.

Five stages, each a pure function: detect the format, locate the references
section, split it into entries, take each entry's identifier, normalise the
identifier to the vocabulary the corpus uses. Stage 2 is where extraction
fails catastrophically when it fails at all, so it reports "not found"
explicitly rather than returning an empty string.
"""

import re
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader

from policy_grapher.sources.document import (
    DocumentSourceError,
    ExtractedDocument,
    ExtractionReport,
)


def pages_of(path: Path) -> list[str]:
    """Each page's text, in reading order — 1-based page numbers are this
    list's index + 1. `text_of` used to flatten this straight to a string and
    throw the boundaries away; phase 2 chunking needs them back to attach a
    real page number to a citation."""
    return [page.extract_text() or "" for page in PdfReader(path).pages]


def text_of(path: Path) -> str:
    """Every page's text, joined by newlines."""
    return "\n".join(pages_of(path))


# The heading is spelled three ways across the sample fixtures: a bare REFERENCES,
# "ENCLOSURE 1" then REFERENCES, and an unnumbered "ENCLOSURE" then REFERENCES.
# Entry markers were consistent where headings were not, so detection keys on them.
_HEADING = re.compile(r"(?:ENCLOSURE(?:\s+\d+)?\s*\n+\s*)?REFERENCES\s*\n", re.IGNORECASE)
# A still older cover runs the heading inline with its first entry — "References:
# (a) DoD Directive 5000.1, ..." — with no standalone REFERENCES line for `_HEADING`
# to find. The lookahead is the whole guard: a heading only counts when a lettered
# entry follows it, which a prose mention of "references" never has.
_INLINE_HEADING = re.compile(r"References:\s*(?=\(\s*[a-z]{1,3}\s*\))", re.IGNORECASE)
_LETTERED = re.compile(r"\(\s*[a-z]{1,3}\s*\)\s+")
_SECTION_END = re.compile(r"\n\s*(?:ENCLOSURE\s+\d+|GLOSSARY|APPENDIX)\s*\n", re.IGNORECASE)
# A cover carrying the inline form may carry none of ENCLOSURE/GLOSSARY/APPENDIX
# anywhere in the document, so `_SECTION_END` finds nothing nearby and the slice
# runs to whichever of those headings happens to sit thousands of characters into
# the body — inventing references out of the directive's own prose. The lettered
# block instead ends at the first *numbered* section heading ("1.  PURPOSE"), which
# `_SECTION_END` does not look for. Used only for the inline form: the five existing
# ratchet fixtures depend on `_SECTION_END`'s current behaviour for the standalone
# REFERENCES-on-its-own-line form, so that pattern is left untouched.
_INLINE_SECTION_END = re.compile(r"\n\s*\d+(?:\.\d+)*\.\s+[A-Z]")
# Every page carries a footer naming the issuance, its date and any change; the last
# one falls inside the slice because the section ends mid-page. Left in, it corrupts
# the final entry, e.g. "...current edition DoDD 5143.01, October 24, 2014 Change 2,
# 04/06/2020 21 GLOSSARY".
_PAGE_FOOTER = re.compile(
    r"\n[^\n]*?DoD[DIM]?\s+[\d.\-A-Z]+,\s+\w+ \d{1,2}, \d{4}\s*"
    r"(?:\n[^\n]*?Change \d+[^\n]*)?\s*(?:GLOSSARY|ENCLOSURE\s+\d+)?\s*$",
    re.IGNORECASE,
)
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
    return [
        re.sub(r"\s*\n\s*", " ", part).strip() for part in _rejoin_open_quotes(raw_parts)
    ]


def _rejoin_open_quotes(parts: list[str]) -> list[str]:
    """Re-attach a fragment that an opener phrase split out of an open title.

    A citation's own quoted title can wrap onto a line beginning with an opener
    ("...Systems Engineering, \u201cDepartment of / Defense Risk, Issue, and
    Opportunity Management Guide..."), which the line-anchored boundary reads as a
    new entry. A new citation cannot begin while the previous title is still open,
    so a part left holding an unclosed quote absorbs the next one.
    """
    joined: list[str] = []
    for part in parts:
        if joined and joined[-1].count("\u201c") > joined[-1].count("\u201d"):
            joined[-1] += part
        else:
            joined.append(part)
    return joined


def locate_references(full: str) -> tuple[str, str | None]:
    """Find the references section and say which format it is.

    Returns ("unknown", None) when no section is found — distinct from an empty
    section, which would look identical downstream and mean something different.
    """
    candidates = sorted(
        [(match, _SECTION_END) for match in _HEADING.finditer(full)]
        + [(match, _INLINE_SECTION_END) for match in _INLINE_HEADING.finditer(full)],
        key=lambda pair: pair[0].start(),
    )
    for match, section_end in candidates:
        body = full[match.end() :]
        end = section_end.search(body)
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
        section = _PAGE_FOOTER.sub("", section)
        if _LETTERED.match(section.lstrip()):
            return "legacy", section
        # A marker phrase alone is not enough: a table-of-contents line can mention
        # "DoD Directive" without citing anything. A real section yields at least one
        # identifier, so require that rather than trusting the phrase.
        if _MODERN_MARKER.search(section[:600]) and any(
            identifier(entry) for entry in split_entries("modern", section)
        ):
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
# Identity is read from the cover page only. Searching the whole document lets a
# CITED issuance win — 850001_2014 names its own cancelled predecessor "DoD Directive
# 8500.01" in the enclosure, which would title a DoDI as a DoDD and hang every edge
# off the wrong node. The bound is the references heading when there is one, since
# nothing after it is cover matter, and a generous fixed fallback otherwise; taking
# the smaller of the two keeps a long classification banner from pushing a real
# header out of range.
_COVER_PAGE_FALLBACK = 2000


def _cover_page(full: str) -> str:
    """The slice of text that is cover matter, not body or references.

    Shared by `document_name` and `effective_date` for the same reason: both
    read facts that are only reliable on the cover, and both would otherwise
    risk matching a body mention (a cited predecessor's own date, e.g.) instead.

    Always at most `_COVER_PAGE_FALLBACK`, even when a references heading exists
    further out. DoD's modern layout puts REFERENCES near the *end* of the
    document — the heading alone bounded almost nothing in practice (measured at
    73-98% of the full document across the sample fixtures), which made
    `effective_date`'s "latest labelled date" scan a whole-document search, free
    to pick up a citation's own date deep in the body. The cost is real: a
    genuine header or date pushed past the fallback by unusually long front
    matter goes unfound. That is the honest failure mode this project prefers —
    see `document_name`'s and `effective_date`'s own docstrings.
    """
    heading = _HEADING.search(full)
    bound = min(heading.start(), _COVER_PAGE_FALLBACK) if heading else _COVER_PAGE_FALLBACK
    return full[:bound]


def document_name(full: str) -> str | None:
    """The issuance's own name, in the corpus's vocabulary.

    The earliest match on the page wins, not the first pattern to match. A cover
    states its own identity at the top and cites other issuances below it, so
    position is the signal and pattern order is noise. Trying `_MODERN_HEADER`
    across the whole cover first let a *cited* modern-format name beat the
    document's own legacy header: DoDD 5000.01 (May 12, 2003) carries the legacy
    "DIRECTIVE / NUMBER 5000.01" at the top and cites "DoD Directive 5000.1" —
    the issuance it cancels — a few lines down, and came back titled 5000.1.
    Every citation edge would then hang off the predecessor's node.

    `_cover_page`'s bound does not cover this on its own: `_HEADING` wants
    "REFERENCES" on a line of its own, and legacy covers run "References:  (a) …"
    inline, so the fallback slice keeps the citation in view.
    """
    cover = _cover_page(full)
    found = [
        match
        for match in (pattern.search(cover) for pattern in (_MODERN_HEADER, _LEGACY_HEADER))
        if match is not None
    ]
    if not found:
        return None

    earliest = min(found, key=lambda match: match.start())
    kind = _ABBREVIATION[earliest.group(1).lower()]
    return f"{kind} {earliest.group(2)}"


# A bare date, in either of the two forms DoD issuances use: "April 1, 2026" and
# "1 April 2026". Not matched on its own — see DATE_PATTERNS below. A cover page
# states three kinds of date, and only two of them are the edition's own: a
# labelled effective date ("Effective: September 9, 2020"), a labelled change date
# ("Change 1 Effective: July 28, 2022", or the bare "Incorporating Change 2,
# April 6, 2020" — no word "Effective" at all) — and, indistinguishable by shape
# alone, an unlabelled date inside a citation of some *other* issuance ("Reissues
# and Cancels: DoD Directive 5000.01, "The Defense Acquisition System," May 12,
# 2003"). Matching a bare date and taking whichever comes first is exactly how
# that citation date wins by position — typography, not a rule. So the date
# patterns are never searched for on their own; they are only ever matched
# anchored to a label (below), which a citation's restated date never carries.
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
)
_DATE_MDY = rf"(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}}),?\s+(?P<year>\d{{4}})"
_DATE_DMY = rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH})\s+(?P<year>\d{{4}})"

# Each entry anchors one of the two date shapes above to a label DoD covers
# actually use. "Effective:?\s+" covers both "Effective: <date>" and the
# colon-less "Incorporating Change 1, Effective <date>"; it also covers
# "Change 1 Effective: <date>" without a separate pattern, since it matches
# wherever "Effective" is immediately followed by a date, regardless of what
# precedes it. The third form carries no word "Effective" at all ("Incorporating
# Change 2, April 6, 2020") and needs its own anchor.
DATE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for date_shape in (_DATE_MDY, _DATE_DMY)
    for pattern in (
        rf"Effective:?\s+{date_shape}",
        rf"Incorporating\s+Change\s+\d+,\s*{date_shape}",
    )
)


def effective_date(cover_text: str) -> date | None:
    """The latest labelled date the cover page states, or None.

    None is a correct and common answer. Guessing a date would put a wrong
    edition boundary into the graph, which is worse than an undated edition —
    version identity falls back to a checksum, which is honest about what we
    could not read.

    "Latest" because the file on disk is whatever the cover page's last change
    says it is: 500001p.pdf's cover carries both the original "Effective:
    September 9, 2020" and "Change 1 Effective: July 28, 2022," and the text
    extracted from it is the Change-1-incorporated edition, not the 2020 base.
    An unlabelled date is never a candidate at all — see DATE_PATTERNS.
    """
    found: list[date] = []
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(cover_text):
            try:
                # Only the calendar date is kept (`.date()`); a cover page states no
                # timezone, and inventing one would be no more honest than guessing
                # the date itself. DTZ007 flags naive datetimes as a rule of thumb,
                # not because a wall-clock instant is wanted here.
                found.append(
                    datetime.strptime(  # noqa: DTZ007
                        f"{match['day']} {match['month']} {match['year']}", "%d %B %Y"
                    ).date()
                )
            except ValueError:
                continue
    return max(found) if found else None


def normalise(name: str) -> str:
    """Map an identifier to the vocabulary the corpus CSV uses."""
    code = _US_CODE.match(name)
    if code:
        return f"United States Code, Title {code.group(1)}"
    issuance = _ISSUANCE.match(name)
    if issuance:
        return f"{_ABBREVIATION[issuance.group(1).lower()]} {issuance.group(2)}"
    return name


def extract_document(path: Path) -> ExtractedDocument:
    """Read one issuance into a document and the documents it cites."""
    try:
        pages = pages_of(path)
    except Exception as exc:  # pypdf raises several unrelated types
        raise DocumentSourceError(f"{path.name!r} could not be read as a PDF.") from exc
    full = "\n".join(pages)

    name = document_name(full)
    if name is None:
        raise DocumentSourceError(
            f"{path.name!r} has no recognisable issuance header; it may not be a DoD issuance."
        )
    date_found = effective_date(_cover_page(full))

    fmt, section = locate_references(full)
    attributed: list[str] = []
    unattributed: list[str] = []
    for entry in split_entries(fmt, section) if section else []:
        found = identifier(entry)
        if found is None:
            unattributed.append(entry)
        else:
            attributed.append(normalise(found))

    skipped = sum(1 for reference in attributed if reference == name)
    references = tuple(sorted({r for r in attributed if r != name}))

    return ExtractedDocument(
        name=name,
        references=references,
        self_references_skipped=skipped,
        effective_date=date_found,
        report=ExtractionReport(
            format=fmt,
            section_found=section is not None,
            attributed=tuple(sorted(set(attributed))),
            unattributed=tuple(unattributed),
        ),
        pages=pages,
    )
