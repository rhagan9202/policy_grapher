# DI-2 Phase 2: Text Storage and Section-Aware Chunking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the documents' actual text into the graph, chunked along the document's own section structure and anchored to page and section path — the substrate every later phase reads from.

**Architecture:** A `:Chunk` carries text, `page`, and `section_path`, hanging off a `:DocumentVersion` by `HAS_CHUNK`. Chunking follows the document's heading hierarchy rather than a fixed window, because a fixed window splits an obligation away from its conditions. A Neo4j full-text index over chunk text lands here too — exact designators are lexical and embeddings handle them badly.

**Tech Stack:** FastAPI, pypdf, neo4j Python driver 6.x, pytest + testcontainers.

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Ontology* (derived layer) and *Corpus* (chunking).

**Depends on:** Phase 1 — `:DocumentVersion` exists and PDF ingest creates one.

## Global Constraints

- Python `>=3.14`; deps via `uv`. Add nothing to `pyproject.toml` — chunking is pure Python over the `pypdf` text layer.
- Ruff enforced **as a test**. Integration tests use real `neo4j:2025.10`; never mock the driver.
- `:Chunk` is **derived**: droppable and rebuildable, never hand-edited. Nothing outside this layer may hold a reference that a rebuild would break.
- Chunk identity is deterministic — `hash(version_id, section_path, ordinal)` — so a rebuild reproduces the same ids and anything anchored to them survives.
- Extraction stays model-free in this phase. No LLM. That arrives in Phase 3.
- Documentation updated in the same change.

## Decisions an executor must not silently change

**1. Chunks never span a section boundary.** A chunk that ends mid-section and begins mid-another is the failure that produces confidently wrong compliance answers — an obligation separated from the scope qualifier that limits it. Sections bound chunks; size only splits *within* a section.

**2. `section_path` is a list, not a string.** `["Chapter 3", "3.2", "3.2.1"]`. A reviewer reading a citation needs the hierarchy, and a string forces every consumer to re-parse it.

**3. Oversized sections split with overlap; undersized ones do not merge.** A 40-word section is a real section and merging it into its neighbour destroys the anchor. Only splitting is allowed, and only when a section exceeds the cap.

**4. Text is stored verbatim.** No normalisation, no whitespace collapsing beyond what `pypdf` already does. A citation must quote what the document says.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/chunking.py` | *Create* — section detection, chunk splitting, identity |
| `backend/src/policy_grapher/chunks.py` | *Create* — writing chunks to the graph, dropping them |
| `backend/src/policy_grapher/db.py` | *Modify* — chunk constraint and full-text index |
| `backend/src/policy_grapher/ingest.py` | *Modify* — chunk during document ingest |
| `backend/src/policy_grapher/models.py` | *Modify* — `ChunkOut` |
| `backend/src/policy_grapher/routers/documents.py` | *Modify* — `GET /documents/{slug}/chunks` |
| `backend/tests/test_chunking.py`, `backend/tests/test_chunks.py` | *Create* |
| `docs/specs/adr/ADR-012-*.md` | *Create* — chunks follow sections, and the derived layer is rebuildable |

---

### Task 1: Section-aware chunking (pure, no database)

**Files:**
- Create: `backend/src/policy_grapher/chunking.py`, `backend/tests/test_chunking.py`

**Interfaces:**
- Produces: `Chunk` (a dataclass: `chunk_id`, `text`, `page`, `section_path`, `ordinal`), and `chunk_pages(pages: list[str], *, version_id: str, max_chars: int = 2000, overlap_chars: int = 200) -> list[Chunk]`

- [ ] **Step 1: Write the failing structure tests**

Create `backend/tests/test_chunking.py`:

```python
from policy_grapher.chunking import chunk_pages, section_heading


def test_a_numbered_heading_is_recognised():
    assert section_heading("3.2. RESPONSIBILITIES.") == "3.2"
    assert section_heading("3.2.1. The Director shall...") == "3.2.1"


def test_a_chapter_heading_is_recognised():
    assert section_heading("CHAPTER 4") == "CHAPTER 4"
    assert section_heading("SECTION 2: POLICY") == "SECTION 2"


def test_ordinary_prose_is_not_a_heading():
    assert section_heading("The Director shall notify the Comptroller.") is None
    assert section_heading("") is None


def test_a_decimal_in_prose_is_not_a_heading():
    """"...within 3.2 percent" must not open a section."""
    assert section_heading("Rates above 3.2 percent require approval.") is None


def test_chunks_never_span_a_section():
    pages = ["3.1. FIRST.\nAlpha text.\n3.2. SECOND.\nBravo text.\n"]
    chunks = chunk_pages(pages, version_id="v")

    paths = [c.section_path for c in chunks]
    assert ["3.1"] in paths and ["3.2"] in paths
    for chunk in chunks:
        assert not ("Alpha" in chunk.text and "Bravo" in chunk.text)


def test_the_section_path_carries_the_hierarchy():
    pages = ["CHAPTER 4\n4.1. SCOPE.\n4.1.2. Detail here.\nBody.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert chunks[-1].section_path == ["CHAPTER 4", "4.1", "4.1.2"]


def test_the_page_number_is_one_indexed_and_tracked():
    chunks = chunk_pages(["1.1. A.\nFirst page.", "1.2. B.\nSecond page."], version_id="v")
    assert {c.page for c in chunks} == {1, 2}


def test_an_oversized_section_splits_with_overlap():
    body = " ".join(f"word{i}" for i in range(2000))
    chunks = chunk_pages([f"5.1. BIG.\n{body}"], version_id="v", max_chars=500, overlap_chars=100)

    assert len(chunks) > 1
    assert all(c.section_path == ["5.1"] for c in chunks)
    # Overlap: the tail of one chunk reappears at the head of the next.
    assert chunks[0].text[-50:] in chunks[1].text


def test_a_tiny_section_is_not_merged_into_its_neighbour():
    """A short section is still a section; merging destroys its anchor."""
    pages = ["6.1. SHORT.\nBrief.\n6.2. NEXT.\nMore text here.\n"]
    chunks = chunk_pages(pages, version_id="v")
    assert ["6.1"] in [c.section_path for c in chunks]


def test_identity_is_deterministic_across_runs():
    pages = ["7.1. A.\nText.\n"]
    first = chunk_pages(pages, version_id="v")
    second = chunk_pages(pages, version_id="v")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_identity_differs_between_versions():
    pages = ["7.1. A.\nText.\n"]
    assert (
        chunk_pages(pages, version_id="a")[0].chunk_id
        != chunk_pages(pages, version_id="b")[0].chunk_id
    )


def test_text_before_any_heading_is_kept_under_a_preamble_path():
    """A cover page has no section number and must not be dropped."""
    chunks = chunk_pages(["Department of Defense Instruction 5000.88\n"], version_id="v")
    assert chunks and chunks[0].section_path == ["(preamble)"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_chunking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.chunking'`

- [ ] **Step 3: Implement the chunker**

Create `backend/src/policy_grapher/chunking.py`:

```python
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
                if found > start:
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
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_chunking.py -v`
Expected: PASS (11 tests). If the hierarchy test fails, check `_push`'s depth rule against the exact headings the test uses before changing the test.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/chunking.py backend/tests/test_chunking.py
git commit -m "feat: chunk policy text along its own section structure"
```

---

### Task 2: Store chunks in the graph

**Files:**
- Create: `backend/src/policy_grapher/chunks.py`, `backend/tests/test_chunks.py`
- Modify: `backend/src/policy_grapher/db.py`

**Interfaces:**
- Consumes: `Chunk` from Task 1
- Produces: `write_chunks(tx, *, version_id, chunks: list[Chunk]) -> int`, `drop_chunks(tx, *, version_id) -> int`

- [ ] **Step 1: Add the constraint and full-text index**

In `backend/src/policy_grapher/db.py`, append to `CONSTRAINTS`:

```python
    (
        "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE"
    ),
)

INDEXES: tuple[str, ...] = (
    # Exact designators ("DoDI 5000.88", "s.14(2)") are lexical. Embeddings are
    # poor at them, so the hybrid retrieval in phase 5 needs this leg.
    (
        "CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS "
        "FOR (c:Chunk) ON EACH [c.text]"
    ),
```

Then extend `apply_constraints` to run `INDEXES` as well, and rename it `apply_schema`,
updating its one caller in `main.py` and the `conftest.py` fixture. Keep a module-level
alias `apply_constraints = apply_schema` **only if** something outside those two references
it — check first with grep, and delete the alias if nothing does.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_chunks.py`:

```python
import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import drop_chunks, write_chunks


def _seed_version(driver, database):
    driver.execute_query(
        "CREATE (d:Document {slug: 'd', name: 'D'})-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: 'v', checksum: 'x', source_uri: 'file:///d.pdf'})",
        database_=database,
    )


@pytest.mark.integration
def test_chunks_attach_to_their_version(clean_graph, database):
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        written = session.execute_write(write_chunks, version_id="v", chunks=chunks)

    assert written == len(chunks)
    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v'})-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN c.section_path AS path, c.page AS page",
        database_=database,
    )
    assert records[0]["path"] == ["1.1"]
    assert records[0]["page"] == 1


@pytest.mark.integration
def test_writing_the_same_chunks_twice_creates_nothing_new(clean_graph, database):
    """Deterministic ids make a rebuild idempotent."""
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == len(chunks)


@pytest.mark.integration
def test_dropping_chunks_leaves_the_version_intact(clean_graph, database):
    """The derived layer is droppable; the canonical layer is not touched."""
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nAlpha.\n"], version_id="v")

    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)
        dropped = session.execute_write(drop_chunks, version_id="v")

    assert dropped == len(chunks)
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Chunk) WITH count(c) AS chunks "
        "MATCH (v:DocumentVersion) RETURN chunks, count(v) AS versions",
        database_=database,
    )
    assert (records[0]["chunks"], records[0]["versions"]) == (0, 1)


@pytest.mark.integration
def test_the_fulltext_index_finds_a_designator(clean_graph, database):
    _seed_version(clean_graph, database)
    chunks = chunk_pages(["1.1. A.\nSee DoDI 5000.88 for detail.\n"], version_id="v")
    with clean_graph.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)

    records, _, _ = clean_graph.execute_query(
        'CALL db.index.fulltext.queryNodes("chunk_text", $q) '
        "YIELD node RETURN node.chunk_id AS id",
        {"q": '"DoDI 5000.88"'},
        database_=database,
    )
    assert records
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_chunks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.chunks'`

- [ ] **Step 4: Implement**

Create `backend/src/policy_grapher/chunks.py`:

```python
"""Chunks in the graph — the first layer that is derived rather than canonical.

Everything here is droppable and rebuildable. Chunk ids are deterministic
(chunking.Chunk), so a rebuild reproduces the same ids and anything anchored to
a chunk survives it. That property is what makes re-extraction safe.
"""

from neo4j import ManagedTransaction

from policy_grapher.chunking import Chunk

WRITE_CHUNKS = """
MATCH (v:DocumentVersion {version_id: $version_id})
UNWIND $chunks AS chunk
MERGE (c:Chunk {chunk_id: chunk.chunk_id})
ON CREATE SET c.text         = chunk.text,
              c.page         = chunk.page,
              c.section_path = chunk.section_path,
              c.ordinal      = chunk.ordinal
MERGE (v)-[:HAS_CHUNK]->(c)
"""

DROP_CHUNKS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk)
DETACH DELETE c
"""


def write_chunks(tx: ManagedTransaction, *, version_id: str, chunks: list[Chunk]) -> int:
    """Attach chunks to a version. Returns how many are now attached."""
    if not chunks:
        return 0
    tx.run(
        WRITE_CHUNKS,
        {
            "version_id": version_id,
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "text": c.text,
                    "page": c.page,
                    "section_path": c.section_path,
                    "ordinal": c.ordinal,
                }
                for c in chunks
            ],
        },
    ).consume()
    return len(chunks)


def drop_chunks(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove a version's chunks. The version and its document are untouched."""
    summary = tx.run(DROP_CHUNKS, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted
```

- [ ] **Step 5: Run tests and commit**

Run: `cd backend && uv run pytest tests/test_chunks.py -v` then the full suite.
Expected: PASS

```bash
git add backend/src/policy_grapher/chunks.py backend/src/policy_grapher/db.py \
        backend/tests/test_chunks.py
git commit -m "feat: chunks live in the graph, droppable and rebuildable"
```

---

### Task 3: Chunk during ingest, and expose them

**Files:**
- Modify: `backend/src/policy_grapher/ingest.py`, `backend/src/policy_grapher/sources/pdf.py`, `backend/src/policy_grapher/models.py`, `backend/src/policy_grapher/routers/documents.py`
- Modify: `backend/tests/test_chunks.py`
- Create: `docs/specs/adr/ADR-012-chunks-follow-sections.md`

**Interfaces:**
- Produces: `GET /documents/{slug}/chunks?version_id=` → `list[ChunkOut]`

- [ ] **Step 1: Write the failing end-to-end test**

Append to `backend/tests/test_chunks.py`:

```python
@pytest.mark.integration
def test_ingesting_a_pdf_stores_its_text(client_with_auth):
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = response.json()["document"]["slug"]

    chunks = client_with_auth.get(f"/documents/{slug}/chunks")
    assert chunks.status_code == 200
    body = chunks.json()
    assert body, "a real DoD issuance must produce at least one chunk"
    assert all(c["text"].strip() for c in body)
    assert all(c["page"] >= 1 for c in body)
    assert any(c["section_path"] != ["(preamble)"] for c in body), (
        "every chunk landing in the preamble means section detection found nothing"
    )
```

That last assertion is the one that matters: chunking that silently degrades to
one giant preamble blob would still return chunks, and would be useless.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_chunks.py -k stores_its_text -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Carry page text through extraction**

`sources/pdf.py` already reads pages via `pypdf` and discards them. Add the page list to
`ExtractedDocument` as `pages: list[str]` so ingest can chunk it. This is the change the
design calls out — the text was always read, only never kept.

- [ ] **Step 4: Chunk inside the ingest transaction**

In `ingest.py`'s `_write_document`, after `merge_version` and `link_supersession`:

```python
    drop_chunks(tx, version_id=version)
    write_chunks(
        tx,
        version_id=version,
        chunks=chunk_pages(extracted.pages, version_id=version),
    )
```

`drop` then `write`, not `merge` alone: a chunker improvement must not leave the previous
run's chunks orphaned beside the new ones. This is the rebuildable-overlay property in
practice. `version` here is the id `merge_version` returned in Phase 1 — it already returns
the resolved `version_id` for exactly this reason, so bind it rather than recomputing it.

- [ ] **Step 5: Add the model and route**

`ChunkOut` in `models.py`:

```python
class ChunkOut(BaseModel):
    chunk_id: str
    text: str
    page: int
    section_path: list[str]
    ordinal: int
```

And in `routers/documents.py`, a `GET /{slug}/chunks` route taking an optional
`version_id` query parameter (defaulting to the newest version), ordered by `ordinal`,
carrying `principal: Principal = Depends(require_principal)` like every other route.

- [ ] **Step 6: Write ADR-012**

Create `docs/specs/adr/ADR-012-chunks-follow-sections.md`. It must state: chunks follow the
document's section hierarchy rather than a fixed window, and why — a window splits an
obligation from its conditions, which is how retrieval produces confident wrong answers;
that oversized sections split with overlap while undersized ones never merge; that
`section_path` is a list because a citation needs the hierarchy; that text is stored
verbatim so a citation can quote it; and that `:Chunk` is the first **derived** label —
droppable, rebuildable, with deterministic ids so a rebuild preserves anything anchored
to it.

- [ ] **Step 7: Run everything and commit**

Run: `cd backend && uv run pytest`
Expected: PASS

```bash
git add backend/src/policy_grapher backend/tests docs/specs/adr/ADR-012-chunks-follow-sections.md
git commit -m "feat: ingest stores the text it used to discard"
```

---

## Done when

- A real DoD PDF ingests into chunks with real `section_path` values, not one preamble blob
- Re-ingesting produces the same chunk ids; a chunker change replaces rather than duplicates
- `drop_chunks` removes the derived layer and leaves versions and documents standing
- The full-text index finds an exact designator
- `GET /documents/{slug}/chunks` requires a principal
- ADR-012 exists; `uv run pytest` passes

Phase 3 (obligation extraction) can start.
