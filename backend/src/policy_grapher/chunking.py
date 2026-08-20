"""Split a document's text along its own section structure.

Fixed-size windows are the obvious approach and the wrong one for policy text:
they split an obligation away from the conditions and scope qualifiers that
limit it, which is exactly how a retrieval layer produces a confident, wrong
compliance answer. Sections bound chunks here; size only splits within one.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

PREAMBLE = "(preamble)"

# "3.2." / "3.2.1." at the start of a line, followed by whitespace. The trailing
# dot and line anchor are what keep "above 3.2 percent" out of the heading set.
NUMBERED = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.\s+\S")
NAMED = re.compile(r"^(?P<kind>CHAPTER|SECTION|APPENDIX|ENCLOSURE)\s+(?P<id>[\dIVXA-Z]+)\b")

# A table-of-contents row: "1.1.  Applicability. ........ 4". It opens with a
# real heading and so is indistinguishable from one by prefix alone; the dot
# leader running to a page number is what gives it away. Four dots, allowing a
# single space between them (extraction sometimes spaces them out), so a
# three-dot ellipsis in prose is not mistaken for a leader.
DOT_LEADER = re.compile(r"\.\s?\.\s?\.\s?\.")

# How many pages a line must repeat on, verbatim, to be page furniture rather
# than content. A running header or footer is on every page of its part; a
# document that genuinely opens the same section twice does so twice.
FURNITURE_PAGES = 3


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    page: int
    section_path: list[str]
    ordinal: int


def section_heading(line: str) -> str | None:
    """The section this line opens, or None if it opens none."""
    stripped = line.strip()
    if not stripped:
        return None
    # A contents row points at a section; it is not one. Reading it as a heading
    # binds the path to the contents page instead of to the body, and chunks a
    # page of dot leaders as if it were document text.
    if DOT_LEADER.search(stripped):
        return None
    named = NAMED.match(stripped)
    if named:
        return f"{named['kind']} {named['id']}"
    numbered = NUMBERED.match(stripped)
    return numbered["number"] if numbered else None


def _push(path: list[str], heading: str) -> list[str]:
    """Place a heading in the hierarchy by its depth.

    "3.2.1" nests under "3.2"; "CHAPTER 4" resets to the top. Depth comes from
    the dot count, so a document that skips a level still nests sensibly.
    """
    if not heading[0].isdigit():
        return [heading]
    # PREAMBLE ("(preamble)") starts with "(", not a digit, so the `kept`
    # filter below -- which only ever drops a *digit*-prefixed ancestor, via
    # `p[0].isdigit()` -- can never remove it. Without this early return,
    # PREAMBLE would ride along as a permanent, phantom ancestor of every
    # section for the rest of the document (e.g. ["(preamble)", "3.1"]
    # instead of ["3.1"]), because "not p[0].isdigit()" is unconditionally
    # true for it and nothing else in `kept` ever re-evaluates it.
    if path == [PREAMBLE]:
        return [heading]
    depth = heading.count(".")
    # A digit-prefixed ancestor is kept only if it is both shallower *and* a
    # genuine numeric-prefix ancestor of `heading` (e.g. "3.2" of "3.2.1").
    # Comparing depth alone lets an unrelated number at the same depth as a
    # still-open ancestor survive -- "10.1" arriving after "9", "9.10",
    # "9.10.2" would otherwise keep "9" (depth 0 < 1) as "10.1"'s parent even
    # though "10.1" has nothing to do with section "9".
    kept = [
        p
        for p in path
        if not p[0].isdigit() or (p.count(".") < depth and heading.startswith(f"{p}."))
    ]
    return [*kept, heading]


def _chunk_id(version_id: str, section_path: list[str], occurrence: int, ordinal: int) -> str:
    """Identity from where a chunk sits in the document's own structure.

    `ordinal` here is the ordinal *within one opening of one section*, not the
    document-global reading-order counter. That distinction is the whole point:
    a document-global ordinal makes a chunk's identity depend on how much text
    precedes it, so adding a paragraph to page 20 renumbers every chunk after
    it (measured on `850001_2014.pdf`: 40 of 125 ids orphaned by a one-paragraph
    insertion). Since the derived layer's entire justification is that it can be
    rebuilt without breaking what anchors to it, an id that survives only a
    byte-identical rebuild is worth very little — the case that matters is an
    *unrelated* edit, or the chunker improvement ADR-012 defers.

    `occurrence` counts how many times this exact `section_path` has already
    opened in this document, because `section_path` is not unique:
    `850001_2014.pdf` opens ["ENCLOSURE 3", "1"] five separate times, and 12 of
    its paths open more than once. Without it, the first chunk of each opening
    would collide on (path, 0).
    """
    key = f"{version_id}|{'/'.join(section_path)}|{occurrence}|{ordinal}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _page_furniture(pages: list[str]) -> set[str]:
    """Lines repeated verbatim on FURNITURE_PAGES pages or more.

    A running header or footer — `ENCLOSURE 2` standing alone at the top or foot
    of every page of an enclosure — matches the heading patterns exactly, so it
    re-opens its section once per page, and each re-open closes whatever section
    was actually being read. Repetition across pages is what distinguishes it
    from a heading, and that is a property of the document, not of the line, so
    it cannot live in `section_heading`.

    Only heading *detection* consults this. The line still travels with the body
    text: ADR-012 stores chunk text verbatim, and a chunk that quietly dropped
    lines would no longer quote its source exactly.
    """
    seen: Counter[str] = Counter()
    for text in pages:
        seen.update({line.strip() for line in text.splitlines() if line.strip()})
    return {line for line, count in seen.items() if count >= FURNITURE_PAGES}


def _split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    # A misconfigured overlap_chars >= max_chars collapses forward progress to
    # ~1 char/iteration (start creeps forward one character at a time), which
    # still terminates but blows a 2000-char section up into ~1900 near-duplicate
    # chunks. Clamp well below max_chars so every iteration makes real progress.
    overlap_chars = max(0, min(overlap_chars, max_chars // 2))
    # A ". " boundary must land past roughly half of max_chars, not merely past
    # `start`. Without a floor, `rfind` can keep re-finding the *same* early
    # boundary as `start` creeps forward (e.g. a heading's own "5.1. " a few
    # characters into the section body), producing a shrinking cascade of
    # near-empty chunks before recovering to full max_chars parts. A prior fix
    # used a bare 50-char constant, which silently disabled sentence-boundary
    # breaking (reintroducing mid-word cuts) for any max_chars near or below
    # 100. Scaling with max_chars -- "a chunk must be at least half the cap" --
    # degrades sensibly at every max_chars instead of only near the defaults.
    min_sentence_offset = max(1, max_chars // 2)
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, before cutting mid-word.
            for boundary in ("\n\n", ". "):
                found = text.rfind(boundary, start, end)
                min_offset = min_sentence_offset if boundary == ". " else 1
                if found - start >= min_offset:
                    end = found + len(boundary)
                    break
        parts.append(text[start:end])
        if end >= len(text):
            break
        start = max(start + 1, end - overlap_chars)
    return parts


def chunk_pages(
    pages: list[str],
    *,
    version_id: str,
    max_chars: int = 2000,
    overlap_chars: int = 200,
) -> list[Chunk]:
    """Chunk a document's pages, one chunk never spanning two sections."""
    sections: list[tuple[list[str], int, list[str], int]] = []
    path: list[str] = [PREAMBLE]
    body: list[str] = []
    page_of_section = 1
    # How many times each section_path has already opened *and produced text*.
    # Counting only sections that emit chunks keeps `occurrence` derivable from
    # the chunks themselves: an opening whose body is blank leaves no trace, so
    # it must not consume a number either.
    occurrences: dict[tuple[str, ...], int] = {}

    def close() -> None:
        if any(line.strip() for line in body):
            key = tuple(path)
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            sections.append((list(path), page_of_section, list(body), occurrence))
        body.clear()

    furniture = _page_furniture(pages)
    for page_number, page_text in enumerate(pages, start=1):
        for line in page_text.splitlines():
            heading = None if line.strip() in furniture else section_heading(line)
            if heading:
                close()
                path = _push(path, heading)
                page_of_section = page_number
            body.append(line)
    close()

    chunks: list[Chunk] = []
    ordinal = 0
    for section_path, page, lines, occurrence in sections:
        parts = _split("\n".join(lines).strip(), max_chars, overlap_chars)
        for within_section, part in enumerate(parts):
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(version_id, section_path, occurrence, within_section),
                    text=part,
                    # `ordinal` is reading order for the /chunks route, and is
                    # deliberately *not* part of the identity above.
                    page=page,
                    section_path=section_path,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return chunks
