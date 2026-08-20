"""Split a document's text along its own section structure.

Fixed-size windows are the obvious approach and the wrong one for policy text:
they split an obligation away from the conditions and scope qualifiers that
limit it, which is exactly how a retrieval layer produces a confident, wrong
compliance answer. Sections bound chunks here; size only splits within one.
"""

import hashlib
import re
from dataclasses import dataclass

PREAMBLE = "(preamble)"

# "3.2." / "3.2.1." at the start of a line, followed by whitespace. The trailing
# dot and line anchor are what keep "above 3.2 percent" out of the heading set.
NUMBERED = re.compile(r"^(?P<number>\d+(?:\.\d+)*)\.\s+\S")
NAMED = re.compile(r"^(?P<kind>CHAPTER|SECTION|APPENDIX|ENCLOSURE)\s+(?P<id>[\dIVXA-Z]+)\b")


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
    # If path is just [PREAMBLE], replace it with the numbered heading
    if path == [PREAMBLE]:
        return [heading]
    depth = heading.count(".")
    kept = [p for p in path if not p[0].isdigit() or p.count(".") < depth]
    return [*kept, heading]


def _chunk_id(version_id: str, section_path: list[str], ordinal: int) -> str:
    key = f"{version_id}|{'/'.join(section_path)}|{ordinal}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _split(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            # Prefer a paragraph break, then a sentence end, before cutting mid-word.
            for boundary in ("\n\n", ". "):
                found = text.rfind(boundary, start, end)
                # Only break on ". " if we have a reasonable chunk size (avoid tiny chunks)
                if found > start and (boundary != ". " or found - start >= 50):
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
    sections: list[tuple[list[str], int, list[str]]] = []
    path: list[str] = [PREAMBLE]
    body: list[str] = []
    page_of_section = 1

    def close(page: int) -> None:
        if any(line.strip() for line in body):
            sections.append((list(path), page_of_section, list(body)))
        body.clear()

    for page_number, page_text in enumerate(pages, start=1):
        for line in page_text.splitlines():
            heading = section_heading(line)
            if heading:
                close(page_number)
                path = _push(path, heading)
                page_of_section = page_number
            body.append(line)
    close(len(pages))

    chunks: list[Chunk] = []
    ordinal = 0
    for section_path, page, lines in sections:
        for part in _split("\n".join(lines).strip(), max_chars, overlap_chars):
            chunks.append(
                Chunk(
                    chunk_id=_chunk_id(version_id, section_path, ordinal),
                    text=part,
                    page=page,
                    section_path=section_path,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return chunks
