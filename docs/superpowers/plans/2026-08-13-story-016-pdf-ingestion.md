# STORY-016 PDF Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `POST /ingest` accepts a DoD issuance PDF, creates the document it describes, and creates `REFERENCES` edges to the documents it cites, reporting what it could not attribute.

**Architecture:** Ingestion splits into two source protocols behind `sources/`. A *manifest* (CSV) becomes many documents, as today. A *document* (PDF) becomes one document plus candidate references and an extraction report. Extraction is a five-stage pipeline — detect format, locate section, split entries, take identifier, normalise — each stage a pure function tested in isolation, because measurement showed section location is where catastrophic failure lives. Both protocols feed the existing `MERGE` layer.

**Tech Stack:** Python 3.14 · FastAPI · Pydantic v2 · neo4j driver v6 · pypdf · uv · pytest · testcontainers · ruff

**Spec:** [`docs/superpowers/specs/2026-08-13-story-016-pdf-extraction-design.md`](../specs/2026-08-13-story-016-pdf-extraction-design.md)
Decisions: [ADR-005](../../specs/adr/ADR-005-slug-assignment-over-the-name-set.md) (incremental slug path), [ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md) (no `reference_role`).

---

## Global Constraints

Copied from the spec and verified against the running system on 2026-08-13. Every task's requirements implicitly include this section.

- **Python `>=3.14`**; **neo4j driver v6** — `driver.execute_query(cypher, params, database_=..., routing_=RoutingControl.READ|WRITE)`, or `session.execute_write(fn, ...)` for the multi-statement ingest transaction. Never `session.run` at module level, never `write_transaction`.
- **Labels and properties are exact:** `Document`, extra label `External`, properties `slug` and `name` only. `reference_role` was removed by ADR-006 — do not reintroduce it.
- **Relationship type is exact:** `REFERENCES`, directed source → target.
- **Baseline to preserve:** 109 backend tests, 35 frontend tests, all passing, output pristine. 37 backend tests run without Docker (`-m "not integration"`) and that must stay true — every extraction test belongs in that subset, since parsing needs no database.
- **Lint is a test.** `tests/test_lint.py` runs `ruff check` over `backend/`. New code must be ruff-clean under the project's config, which exempts `fastapi.Depends`/`fastapi.Query` from B008 and nothing else.
- **Docker socket access needs `sg docker -c "..."`** on this machine — the shell session predates its `docker` group membership. This must never appear in committed files.
- **Fixtures live at `data/samples/`** and are committed: `500001p.pdf` (DoDD 5000.01), `500088p.pdf` (DoDI 5000.88), `514301p.pdf` (DoDD 5143.01), `818001m.pdf` (DoDM 8180.01), `850001_2014.pdf` (DoDI 8500.01), plus `dod_policy_references_08122026.csv`.
- **`DATA_DIR` is `/data/samples`**, hardcoded in `docker-compose.yml` to agree with the bind mount. `SAMPLE_CSV` must stay a bare filename — `resolve_csv_path` refuses subpaths deliberately.
- Corpus facts, unchanged: 23 corpus documents, 415 external, **438** total, **672** `REFERENCES` edges, 72 corpus→corpus.
- **Extraction is deterministic.** No spaCy, no local or hosted model anywhere in the extraction path. Ingest idempotency (STORY-003) depends on it.

---

## File Structure

```
backend/src/policy_grapher/
  sources/__init__.py     NEW — dispatch by extension
  sources/manifest.py     NEW — parse_corpus, moved verbatim from csv_source.py
  sources/document.py     NEW — ExtractedDocument, ExtractionReport
  sources/pdf.py          NEW — the five extraction stages
  csv_source.py           DELETED — moved to sources/manifest.py
  ingest.py               MODIFIED — + ingest_document, dispatch in ingest_file
  models.py               MODIFIED — + source discriminator, DocumentIngestResult
  main.py                 MODIFIED — import moves
  routers/admin.py        MODIFIED — import moves, union response model

backend/tests/
  test_csv_source.py      MODIFIED — import moves only
  test_ingest.py          MODIFIED — import moves only
  test_graph.py           MODIFIED — import moves only
  test_pdf_stages.py      NEW — the five stages, no container
  test_pdf_extraction.py  NEW — extract_document end to end, no container
  test_pdf_ingest.py      NEW — merge layer and endpoint, integration
  test_extraction_ratchet.py  NEW — per-document match floors, no container
```

---

## Task 1: Move `csv_source.py` behind the `sources/` seam

Pure restructure. No behaviour changes. The verification is that all 109 existing tests pass untouched apart from import lines.

**Files:**
- Create: `backend/src/policy_grapher/sources/__init__.py`, `sources/manifest.py`
- Delete: `backend/src/policy_grapher/csv_source.py`
- Modify: `backend/src/policy_grapher/ingest.py:7`, `main.py:8`, `routers/admin.py:5`, `tests/test_csv_source.py:5`, `tests/test_ingest.py:6`, `tests/test_graph.py:5`

**Interfaces:**
- Produces: `sources.manifest.parse_corpus(path: Path) -> ParsedCorpus`, `sources.manifest.resolve_csv_path(filename: str, data_dir: Path) -> Path`, `sources.manifest.CsvSourceError`, `sources.manifest.ParsedCorpus`, `sources.manifest.CorpusRow`, `sources.manifest.canonical_name(name: str) -> str`. All identical to their `csv_source` originals.

- [ ] **Step 1: Move the file with git so history follows it**

```bash
cd /home/rhagan/policy_grapher
mkdir -p backend/src/policy_grapher/sources
touch backend/src/policy_grapher/sources/__init__.py
git mv backend/src/policy_grapher/csv_source.py backend/src/policy_grapher/sources/manifest.py
```

Do not edit the file's contents. Its module docstring still describes exactly what it does.

- [ ] **Step 2: Update the six import sites**

`backend/src/policy_grapher/ingest.py` line 7:

```python
from policy_grapher.sources.manifest import ParsedCorpus, parse_corpus, resolve_csv_path
```

`backend/src/policy_grapher/main.py` line 8 and `backend/src/policy_grapher/routers/admin.py` line 5:

```python
from policy_grapher.sources.manifest import CsvSourceError
```

`backend/tests/test_csv_source.py` line 5:

```python
from policy_grapher.sources.manifest import (
```

`backend/tests/test_ingest.py` line 6 and `backend/tests/test_graph.py` line 5:

```python
from policy_grapher.sources.manifest import parse_corpus
```

- [ ] **Step 3: Run the whole backend suite**

```bash
cd backend && sg docker -c "uv run pytest -q"
```

Expected: **109 passed**, zero warnings. If any test fails, the move changed behaviour — fix the move, never the test.

- [ ] **Step 4: Confirm the container-free suite still runs**

```bash
cd backend && uv run pytest -m "not integration" -q
```

Expected: 37 passed, no container started.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher backend/tests
git commit -m "refactor: move csv_source behind the sources/ seam as manifest.py"
```

---

## Task 2: Add `pypdf` and extract text from a fixture

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/src/policy_grapher/sources/pdf.py`, `backend/tests/test_pdf_stages.py`

**Interfaces:**
- Produces: `sources.pdf.text_of(path: Path) -> str` — the concatenated text of every page, pages joined by `"\n"`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pdf_stages.py`:

```python
"""The five extraction stages. No database, so this stays outside the integration mark."""

from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

MODERN = SAMPLES / "500001p.pdf"      # DoDD 5000.01
LEGACY = SAMPLES / "850001_2014.pdf"  # DoDI 8500.01


def test_text_of_reads_every_page():
    text = pdf.text_of(MODERN)

    assert "DOD DIRECTIVE 5000.01" in text
    assert "THE DEFENSE ACQUISITION SYSTEM" in text
    # 17 pages of content, not just the first
    assert len(text) > 10_000
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.sources.pdf'`.

- [ ] **Step 3: Add the dependency**

In `backend/pyproject.toml`, add to the `dependencies` list (not the dev group — extraction is production code):

```toml
    "pypdf>=6.0",
```

Then:

```bash
cd backend && uv sync
```

- [ ] **Step 4: Write the minimal implementation**

`backend/src/policy_grapher/sources/pdf.py`:

```python
"""Extract a DoD issuance PDF into a document and its cited references.

Five stages, each a pure function: detect the format, locate the references
section, split it into entries, take each entry's identifier, normalise the
identifier to the vocabulary the corpus uses. Stage 2 is where extraction
fails catastrophically when it fails at all, so it reports "not found"
explicitly rather than returning an empty string.
"""

from pathlib import Path

from pypdf import PdfReader


def text_of(path: Path) -> str:
    """Every page's text, joined by newlines."""
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py
git commit -m "feat: read DoD issuance PDFs with pypdf"
```

---

## Task 3: Detect the format and locate the references section

The risky stage. Three heading spellings appear across five fixtures, and both catastrophic failures measured during design happened here.

**Files:**
- Modify: `backend/src/policy_grapher/sources/pdf.py`, `backend/tests/test_pdf_stages.py`

**Interfaces:**
- Consumes: `text_of`.
- Produces: `sources.pdf.locate_references(full: str) -> tuple[str, str | None]` returning `(format, section)` where format is `"legacy"`, `"modern"` or `"unknown"`, and section is `None` when no references section was found.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pdf_stages.py`:

```python
def test_legacy_document_is_detected_by_its_lettered_entries():
    fmt, section = pdf.locate_references(pdf.text_of(LEGACY))

    assert fmt == "legacy"
    assert section is not None
    assert "(a) DoD Directive 8500.01" in section


def test_modern_document_is_detected_as_a_flat_list():
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    assert fmt == "modern"
    assert section is not None
    assert "DoD Directive 1322.18" in section


def test_the_section_is_the_enclosure_not_a_body_mention():
    """A legacy document says "References: See Enclosure 1" in its body and mentions
    "Reference (a)" dozens of times. Matching either scores zero."""
    section = pdf.locate_references(pdf.text_of(LEGACY))[1]

    assert section is not None
    assert "See Enclosure" not in section
    assert section.lstrip().startswith("(a)")


def test_a_document_with_no_references_section_reports_not_found():
    fmt, section = pdf.locate_references("A document with no references at all.")

    assert fmt == "unknown"
    assert section is None
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: FAIL — `AttributeError: module 'policy_grapher.sources.pdf' has no attribute 'locate_references'`.

- [ ] **Step 3: Implement**

Add to `backend/src/policy_grapher/sources/pdf.py`:

```python
import re

# The heading is spelled three ways across the sample fixtures: a bare REFERENCES,
# "ENCLOSURE 1" then REFERENCES, and an unnumbered "ENCLOSURE" then REFERENCES.
# Entry markers were consistent where headings were not, so detection keys on them.
_HEADING = re.compile(r"(?:ENCLOSURE(?:\s+\d+)?\s*\n+\s*)?REFERENCES\s*\n", re.IGNORECASE)
_LETTERED = re.compile(r"\(\s*[a-z]{1,3}\s*\)\s+")
_SECTION_END = re.compile(r"\n\s*(?:ENCLOSURE\s+\d+|GLOSSARY|APPENDIX)\s*\n", re.IGNORECASE)


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
        if _LETTERED.match(section.lstrip()):
            return "legacy", section
        # A modern section lists citations directly; a body mention does not.
        if re.search(r"(?:DoD (?:Directive|Instruction|Manual)|Public Law)\s", section[:600]):
            return "modern", section
    return "unknown", None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Check the other three fixtures locate too**

```bash
cd backend && uv run python -c "
from pathlib import Path
from policy_grapher.sources import pdf
s = Path('../data/samples')
for name in ['500001p.pdf','500088p.pdf','514301p.pdf','818001m.pdf','850001_2014.pdf']:
    fmt, sec = pdf.locate_references(pdf.text_of(s/name))
    print(f'{name:<18} {fmt:<8} {\"found\" if sec else \"NOT FOUND\"} {len(sec) if sec else 0}')
"
```

Expected: all five report a format and a non-empty section. `514301p.pdf` is the one that failed during design with an empty slice — if it reports NOT FOUND or a very short section, fix `locate_references` before continuing. Record the five lines of output in the report.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py
git commit -m "feat: locate the references section and detect issuance format"
```

---

## Task 4: Split the section into entries

**Files:**
- Modify: `backend/src/policy_grapher/sources/pdf.py`, `backend/tests/test_pdf_stages.py`

**Interfaces:**
- Consumes: `locate_references`.
- Produces: `sources.pdf.split_entries(fmt: str, section: str) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pdf_stages.py`:

```python
def test_legacy_entries_split_on_their_letter_markers():
    fmt, section = pdf.locate_references(pdf.text_of(LEGACY))

    entries = pdf.split_entries(fmt, section)

    assert len(entries) > 100  # DoDI 8500.01 cites 114
    assert entries[0].startswith("DoD Directive 8500.01")
    assert not any(entry.startswith("(") for entry in entries)


def test_modern_entries_split_at_identifier_boundaries():
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    entries = pdf.split_entries(fmt, section)

    assert any(entry.startswith("DoD Directive 1322.18") for entry in entries)
    assert any(entry.startswith("Military-Standard 882E") for entry in entries)


def test_wrapped_lines_are_rejoined_into_one_entry():
    """Entries wrap mid-citation in the source PDF; a split on newlines would
    cut titles in half."""
    fmt, section = pdf.locate_references(pdf.text_of(MODERN))

    entries = pdf.split_entries(fmt, section)

    wrapped = [e for e in entries if e.startswith("DoD Directive 5124.02")]
    assert wrapped, "expected the entry that wraps across two lines"
    assert "USD(P&R)" in wrapped[0]
    assert "\n" not in wrapped[0]
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: FAIL — no attribute `split_entries`.

- [ ] **Step 3: Implement**

Add to `backend/src/policy_grapher/sources/pdf.py`:

```python
# Modern sections have no per-entry marker, so entries are cut at the point a new
# citation starts. These are the openers seen across the sample corpus.
_MODERN_BOUNDARY = re.compile(
    r"(?=(?:DoD |Public Law |Military-?Standard |Executive Order |United States Code|"
    r"Title \d|Section \d|Chairman |Under Secretary |Deputy Secretary |Secretary of |"
    r"Assistant Secretary |Director |Federal |National |Department of |Joint |"
    r"Office of |Committee |Code of Federal|Administrative |Directive-[Tt]ype |Defense ))"
)


def split_entries(fmt: str, section: str) -> list[str]:
    """One string per citation, with the source's line wrapping undone."""
    flat = re.sub(r"\s*\n\s*", " ", section).strip()
    if fmt == "legacy":
        parts = _LETTERED.split(flat)
        # split() yields [before-first-marker, entry, entry, ...]
        return [part.strip() for part in parts[1:] if part.strip()]
    return [part.strip() for part in _MODERN_BOUNDARY.split(flat) if part.strip()]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py
git commit -m "feat: split a references section into citation entries"
```

---

## Task 5: Take each entry's identifier and normalise it

**Files:**
- Modify: `backend/src/policy_grapher/sources/pdf.py`, `backend/tests/test_pdf_stages.py`

**Interfaces:**
- Produces: `sources.pdf.identifier(entry: str) -> str | None`, `sources.pdf.normalise(name: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pdf_stages.py`:

```python
@pytest.mark.parametrize(
    "entry,expected",
    [
        ('DoD Directive 1322.18, “Military Training,” October 3, 2019', "DoD Directive 1322.18"),
        ('Military-Standard 882E, “DoD Standard Practice,” May 11, 2012', "Military-Standard 882E"),
        ('DoD Directive 5143.01, “USD(I),” November 23, 2005 (hereby cancelled)', "DoD Directive 5143.01"),
        ("Title 10, United States Code", "Title 10, United States Code"),
    ],
)
def test_identifier_is_the_text_before_the_quoted_title(entry, expected):
    assert pdf.identifier(entry) == expected


def test_an_entry_with_neither_identifier_nor_recognised_shape_is_unattributable():
    entry = '“Summary of the 2018 National Defense Strategy,” 2018'

    assert pdf.identifier(entry) is None


@pytest.mark.parametrize(
    "name,expected",
    [
        ("DoD Directive 5000.01", "DoDD 5000.01"),
        ("DoD Instruction 8500.01", "DoDI 8500.01"),
        ("DoD Manual 8180.01", "DoDM 8180.01"),
        ("Title 10, United States Code", "United States Code, Title 10"),
        ("Public Law 116-283", "Public Law 116-283"),
        ("Military-Standard 882E", "Military-Standard 882E"),
    ],
)
def test_normalise_maps_to_the_corpus_vocabulary(name, expected):
    assert pdf.normalise(name) == expected
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: FAIL — no attribute `identifier`.

- [ ] **Step 3: Implement**

Add to `backend/src/policy_grapher/sources/pdf.py`:

```python
_QUOTED_TITLE = re.compile(r"(.+?),\s*[“\"]")
# Entries that carry no quoted title at all, e.g. "Title 10, United States Code".
_CODE_CITATION = re.compile(r"((?:Title|Section)\s+[\dA-Za-z().]+,\s*United States Code)")
_ISSUANCE = re.compile(r"^DoD\s+(Directive|Instruction|Manual)\s+([0-9][0-9.\-]*[A-Z]?)$", re.IGNORECASE)
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


def normalise(name: str) -> str:
    """Map an identifier to the vocabulary the corpus CSV uses."""
    code = _US_CODE.match(name)
    if code:
        return f"United States Code, Title {code.group(1)}"
    issuance = _ISSUANCE.match(name)
    if issuance:
        return f"{_ABBREVIATION[issuance.group(1).lower()]} {issuance.group(2)}"
    return name
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: PASS, 19 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py
git commit -m "feat: take and normalise a citation's identifier"
```

---

## Task 6: Read the document's own identity from its header

**Files:**
- Modify: `backend/src/policy_grapher/sources/pdf.py`, `backend/tests/test_pdf_stages.py`

**Interfaces:**
- Produces: `sources.pdf.document_name(full: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pdf_stages.py`:

```python
def test_modern_header_names_the_document_on_one_line():
    assert pdf.document_name(pdf.text_of(MODERN)) == "DoDD 5000.01"


def test_legacy_header_splits_the_type_and_number_across_lines():
    """A legacy cover page reads "Department of Defense / DIRECTIVE / NUMBER 5143.01"."""
    legacy_directive = SAMPLES / "514301p.pdf"

    assert pdf.document_name(pdf.text_of(legacy_directive)) == "DoDD 5143.01"


def test_a_manual_is_named_DoDM():
    assert pdf.document_name(pdf.text_of(SAMPLES / "818001m.pdf")) == "DoDM 8180.01"


def test_text_with_no_recognisable_header_has_no_name():
    assert pdf.document_name("Some other document entirely.") is None
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: FAIL — no attribute `document_name`.

- [ ] **Step 3: Implement**

Add to `backend/src/policy_grapher/sources/pdf.py`:

```python
# Modern cover page: "DOD DIRECTIVE 5000.01" on one line.
_MODERN_HEADER = re.compile(
    r"DOD\s+(DIRECTIVE|INSTRUCTION|MANUAL)\s+([0-9][0-9.\-]*[A-Z]?)", re.IGNORECASE
)
# Legacy cover page: "DIRECTIVE" ... "NUMBER 5143.01", separated by blank lines.
_LEGACY_HEADER = re.compile(
    r"\b(DIRECTIVE|INSTRUCTION|MANUAL)\b\s*\n[\s\S]{0,200}?NUMBER\s+([0-9][0-9.\-]*[A-Z]?)",
    re.IGNORECASE,
)


def document_name(full: str) -> str | None:
    """The issuance's own name, in the corpus's vocabulary."""
    for pattern in (_MODERN_HEADER, _LEGACY_HEADER):
        match = pattern.search(full)
        if match:
            kind = _ABBREVIATION[match.group(1).lower()]
            return f"{kind} {match.group(2)}"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_pdf_stages.py -v
```

Expected: PASS, 23 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/sources/pdf.py backend/tests/test_pdf_stages.py
git commit -m "feat: read an issuance's own identity from its cover page"
```

---

## Task 7: Assemble `extract_document`

**Files:**
- Create: `backend/src/policy_grapher/sources/document.py`, `backend/tests/test_pdf_extraction.py`
- Modify: `backend/src/policy_grapher/sources/pdf.py`, `sources/__init__.py`

**Interfaces:**
- Consumes: every stage from Tasks 2–6.
- Produces:
  - `sources.document.ExtractionReport` — frozen dataclass, fields `format: str`, `section_found: bool`, `attributed: tuple[str, ...]`, `unattributed: tuple[str, ...]`.
  - `sources.document.ExtractedDocument` — frozen dataclass, fields `name: str`, `references: tuple[str, ...]`, `self_references_skipped: int`, `report: ExtractionReport`.
  - `sources.document.DocumentSourceError(ValueError)`.
  - `sources.pdf.extract_document(path: Path) -> ExtractedDocument`.
  - `sources.is_document_source(path: Path) -> bool` — True for `.pdf`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pdf_extraction.py`:

```python
"""extract_document end to end. Still no database."""

from pathlib import Path

import pytest

from policy_grapher.sources import pdf
from policy_grapher.sources.document import DocumentSourceError

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_a_modern_issuance_yields_its_name_and_references():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert result.name == "DoDD 5000.01"
    assert "DoDD 1322.18" in result.references
    assert "Military-Standard 882E" in result.references
    assert result.report.format == "modern"
    assert result.report.section_found is True


def test_references_are_sorted_and_unique():
    result = pdf.extract_document(SAMPLES / "850001_2014.pdf")

    assert list(result.references) == sorted(set(result.references))


def test_a_self_reference_is_skipped_and_counted():
    """DoDD 5143.01 lists its own cancelled prior version as entry (a)."""
    result = pdf.extract_document(SAMPLES / "514301p.pdf")

    assert result.name == "DoDD 5143.01"
    assert "DoDD 5143.01" not in result.references
    assert result.self_references_skipped == 1


def test_a_document_that_cites_no_version_of_itself_skips_nothing():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert result.self_references_skipped == 0


def test_entries_that_cannot_be_attributed_are_reported_verbatim():
    result = pdf.extract_document(SAMPLES / "500001p.pdf")

    assert any(
        "National Defense Strategy" in entry for entry in result.report.unattributed
    ), result.report.unattributed


def test_a_pdf_with_no_header_is_refused():
    with pytest.raises(DocumentSourceError):
        pdf.extract_document(SAMPLES / "dod_policy_references_08122026.csv")
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && uv run pytest tests/test_pdf_extraction.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.sources.document'`.

- [ ] **Step 3: Write the shared types**

`backend/src/policy_grapher/sources/document.py`:

```python
"""The single-document source protocol.

A manifest (CSV) becomes many documents; a document (PDF) becomes one. The two
are different operations, so they have different protocols — see the STORY-016
design. Extraction is partial by nature, so what it could not attribute travels
with the result rather than being dropped.
"""

from dataclasses import dataclass


class DocumentSourceError(ValueError):
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
```

- [ ] **Step 4: Assemble the stages**

Add to `backend/src/policy_grapher/sources/pdf.py`:

```python
from policy_grapher.sources.document import (
    DocumentSourceError,
    ExtractedDocument,
    ExtractionReport,
)


def extract_document(path: Path) -> ExtractedDocument:
    """Read one issuance into a document and the documents it cites."""
    try:
        full = text_of(path)
    except Exception as exc:  # pypdf raises several unrelated types
        raise DocumentSourceError(f"{path.name!r} could not be read as a PDF.") from exc

    name = document_name(full)
    if name is None:
        raise DocumentSourceError(
            f"{path.name!r} has no recognisable issuance header; it may not be a DoD issuance."
        )

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
        report=ExtractionReport(
            format=fmt,
            section_found=section is not None,
            attributed=tuple(sorted(set(attributed))),
            unattributed=tuple(unattributed),
        ),
    )
```

- [ ] **Step 5: Add the dispatcher**

`backend/src/policy_grapher/sources/__init__.py`:

```python
"""Ingestion sources. A manifest becomes many documents; a document becomes one."""

from pathlib import Path

DOCUMENT_SUFFIXES = {".pdf"}


def is_document_source(path: Path) -> bool:
    """True when the file is a single policy document rather than a manifest."""
    return path.suffix.lower() in DOCUMENT_SUFFIXES
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && uv run pytest tests/test_pdf_extraction.py -v
```

Expected: PASS, 6 tests. If `test_a_self_reference_is_skipped_and_counted` fails, the section slice for `514301p.pdf` is wrong — revisit Task 3 rather than weakening this test, because the same bug scored 0/70 during design.

- [ ] **Step 7: Run the whole suite and the container-free subset**

```bash
cd backend && sg docker -c "uv run pytest -q"
cd backend && uv run pytest -m "not integration" -q
```

Expected: everything passes; the new extraction tests are in the container-free subset.

- [ ] **Step 8: Commit**

```bash
git add backend/src/policy_grapher/sources backend/tests/test_pdf_extraction.py
git commit -m "feat: extract a document and its references from a DoD issuance PDF"
```

---

## Task 8: Measure against the oracle and set the ratchet floors

The spec deliberately left these numbers unset. Now the parser exists, so measure and pin.

**Files:**
- Create: `backend/tests/test_extraction_ratchet.py`

**Interfaces:**
- Consumes: `sources.pdf.extract_document`, `sources.manifest.parse_corpus`.

- [ ] **Step 1: Measure what the parser actually achieves**

```bash
cd backend && uv run python -c "
import ast, csv
from pathlib import Path
from policy_grapher.sources import pdf
s = Path('../data/samples')
truth = {}
with (s/'dod_policy_references_08122026.csv').open(newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        truth[row['Document Name'].strip()] = set(ast.literal_eval(row['References'] or '[]'))
docs = {'500001p.pdf':'DoDD 5000.01','500088p.pdf':'DoDI 5000.88','514301p.pdf':'DoDD 5143.01','818001m.pdf':'DoDM 8180.01','850001_2014.pdf':'DoDI 8500.01'}
for f, n in docs.items():
    got = set(pdf.extract_document(s/f).references)
    want = truth[n] - {n}
    hit = len(want & got)
    print(f'{n:<15} {hit:>3}/{len(want):<4} {100*hit/len(want):>5.1f}%  spurious {len(got-want)}')
"
```

Record the five percentages. These become the floors, **rounded down to the nearest 5%** so ordinary variation does not break the build.

- [ ] **Step 2: Write the ratchet test using the measured floors**

`backend/tests/test_extraction_ratchet.py`. Replace each `0.00` with the measured floor from Step 1 — do not guess them, and do not set a floor above what was measured:

```python
"""Extraction quality as a number that fails the build when it regresses.

Floors are what the parser achieved when written, rounded down to the nearest 5%.
They may only be raised. Raising one is the correct response to improving the
parser; lowering one needs a reason in the commit message.
"""

import ast
import csv
from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
CORPUS = SAMPLES / "dod_policy_references_08122026.csv"

# fixture -> (corpus name, minimum fraction of that document's references we must find)
FLOORS = {
    "500001p.pdf": ("DoDD 5000.01", 0.00),
    "500088p.pdf": ("DoDI 5000.88", 0.00),
    "514301p.pdf": ("DoDD 5143.01", 0.00),
    "818001m.pdf": ("DoDM 8180.01", 0.00),
    "850001_2014.pdf": ("DoDI 8500.01", 0.00),
}


def expected_references() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    with CORPUS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["Document Name"].strip()
            out[name] = set(ast.literal_eval(row["References"] or "[]")) - {name}
    return out


@pytest.mark.parametrize("filename", sorted(FLOORS))
def test_extraction_meets_its_floor(filename):
    corpus_name, floor = FLOORS[filename]
    expected = expected_references()[corpus_name]

    found = set(pdf.extract_document(SAMPLES / filename).references)

    matched = len(expected & found) / len(expected)
    assert matched >= floor, (
        f"{corpus_name}: matched {matched:.0%}, floor is {floor:.0%}. "
        f"Missing: {sorted(expected - found)[:10]}"
    )
```

- [ ] **Step 3: Run it**

```bash
cd backend && uv run pytest tests/test_extraction_ratchet.py -v
```

Expected: PASS, 5 tests. It passes by construction — the floors came from this parser. Its value is the next change, not this one, so this is the one test in the plan that does not follow red-green. Say so in the report rather than presenting it as a caught bug.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_extraction_ratchet.py
git commit -m "test: pin extraction match rates as floors that can only rise"
```

---

## Task 9: Merge one extracted document into the graph

**Files:**
- Modify: `backend/src/policy_grapher/ingest.py`
- Create: `backend/tests/test_pdf_ingest.py`

**Interfaces:**
- Consumes: `sources.pdf.extract_document`, `documents.allocate_slug(driver, database, name) -> str`.
- Produces: `ingest.ingest_document(driver, database, extracted: ExtractedDocument) -> tuple[str, int, int]` returning `(slug, nodes_created, relationships_created)`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_pdf_ingest.py`:

```python
from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_document
from policy_grapher.sources import pdf

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_ingesting_a_pdf_creates_the_document_and_its_edges(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    slug, nodes, relationships = ingest_document(clean_graph, database, extracted)

    assert slug == "dodd-5000-01"
    assert nodes == 1 + len(extracted.references)
    assert relationships == len(extracted.references)


def test_cited_documents_are_created_external(clean_graph, database):
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'dodd-5000-01'})-[:REFERENCES]->(t) "
        "RETURN count(t) AS cited, sum(CASE WHEN t:External THEN 1 ELSE 0 END) AS external",
        database_=database,
    )
    assert records[0]["cited"] == len(extracted.references)
    assert records[0]["external"] == len(extracted.references)


def test_reingesting_the_same_pdf_creates_nothing_new(clean_graph, database):
    """STORY-003's invariant, on the document path."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")
    ingest_document(clean_graph, database, extracted)

    slug, nodes, relationships = ingest_document(clean_graph, database, extracted)

    assert (slug, nodes, relationships) == ("dodd-5000-01", 0, 0)


def test_the_ingested_document_is_not_external(clean_graph, database):
    """It was cited by nothing, but it is a corpus document, not a citation target."""
    extracted = pdf.extract_document(SAMPLES / "500001p.pdf")

    ingest_document(clean_graph, database, extracted)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'dodd-5000-01'}) RETURN d:External AS is_external",
        database_=database,
    )
    assert records[0]["is_external"] is False
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
```

Expected: FAIL — `ImportError: cannot import name 'ingest_document'`.

- [ ] **Step 3: Implement**

Add to `backend/src/policy_grapher/ingest.py`:

```python
from policy_grapher.documents import allocate_slug
from policy_grapher.sources.document import ExtractedDocument

MERGE_DOCUMENT = """
MERGE (d:Document {slug: $slug})
SET d.name = $name
REMOVE d:External
"""

MERGE_CITED = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
ON CREATE SET d.name = doc.name, d:External
"""


def _write_document(
    tx: ManagedTransaction, *, slug: str, name: str, cited: list[dict], edges: list[dict]
) -> tuple[int, int]:
    nodes_created = tx.run(MERGE_DOCUMENT, {"slug": slug, "name": name}).consume(
    ).counters.nodes_created
    if cited:
        nodes_created += tx.run(MERGE_CITED, {"docs": cited}).consume().counters.nodes_created
    relationships_created = 0
    if edges:
        relationships_created = tx.run(
            MERGE_EDGES, {"edges": edges}
        ).consume().counters.relationships_created
    return nodes_created, relationships_created


def ingest_document(
    driver: Driver, database: str, extracted: ExtractedDocument
) -> tuple[str, int, int]:
    """Merge one extracted document and the documents it cites.

    Slugs come from allocate_slug, not assign_slugs: a document arriving alone is
    ADR-005's incremental case, where the incumbent keeps its bare slug.
    """
    slug = allocate_slug(driver, database, extracted.name)
    cited = [
        {"slug": allocate_slug(driver, database, name), "name": name}
        for name in extracted.references
    ]
    edges = [{"source": slug, "target": entry["slug"]} for entry in cited]

    with driver.session(database=database) as session:
        nodes_created, relationships_created = session.execute_write(
            _write_document, slug=slug, name=extracted.name, cited=cited, edges=edges
        )
    return slug, nodes_created, relationships_created
```

Note `ON CREATE SET` on `MERGE_CITED`: a cited document that already exists as a corpus document must not be relabelled `:External`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
```

Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/src/policy_grapher/ingest.py backend/tests/test_pdf_ingest.py
git commit -m "feat: merge one extracted document and its citations into the graph"
```

---

## Task 10: Dispatch on extension at `POST /ingest`

**Files:**
- Modify: `backend/src/policy_grapher/models.py`, `ingest.py`, `routers/admin.py`
- Modify: `backend/tests/test_pdf_ingest.py`

**Interfaces:**
- Produces:
  - `models.DocumentRef` — `slug: str`, `name: str`.
  - `models.DocumentIngestResult` — `source: Literal["document"]`, `format: str`, `document: DocumentRef`, `nodes_created: int`, `relationships_created: int`, `references_attributed: int`, `references_unattributed: list[str]`, `self_references_skipped: int`.
  - `models.IngestResult` gains `source: Literal["manifest"] = "manifest"`.
  - `ingest.ingest_file(driver, database, filename, data_dir) -> IngestResult | DocumentIngestResult`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pdf_ingest.py`:

```python
def test_posting_a_pdf_filename_ingests_it(client_with_graph):
    response = client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "document"
    assert body["format"] == "modern"
    assert body["document"]["slug"] == "dodd-5000-01"
    assert body["references_attributed"] > 0
    assert isinstance(body["references_unattributed"], list)


def test_the_csv_response_still_says_manifest(client_with_graph):
    response = client_with_graph.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = response.json()
    assert body["source"] == "manifest"
    assert body["nodes_created"] == 438
    assert body["relationships_created"] == 672


def test_an_unreadable_pdf_is_a_400(client_with_graph, tmp_path, monkeypatch):
    """A PDF with no issuance header is a client error, not a 500."""
    from policy_grapher.sources.document import DocumentSourceError
    from policy_grapher import ingest as ingest_module

    def refuse(path):
        raise DocumentSourceError("no recognisable issuance header")

    monkeypatch.setattr(ingest_module.pdf, "extract_document", refuse)

    response = client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    assert response.status_code == 400
    assert "header" in response.json()["detail"]
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
```

Expected: FAIL — `KeyError: 'source'`.

- [ ] **Step 3: Add the models**

In `backend/src/policy_grapher/models.py`, add `Literal` to the typing import and change `IngestResult`, then append the two new models after it:

```python
from typing import Literal


class IngestResult(BaseModel):
    source: Literal["manifest"] = "manifest"
    nodes_created: int
    relationships_created: int
    self_references_skipped: int
    suspected_duplicates: list[list[str]] = Field(default_factory=list)


class DocumentRef(BaseModel):
    slug: str
    name: str


class DocumentIngestResult(BaseModel):
    source: Literal["document"] = "document"
    format: str
    document: DocumentRef
    nodes_created: int
    relationships_created: int
    references_attributed: int
    references_unattributed: list[str] = Field(default_factory=list)
    self_references_skipped: int
```

- [ ] **Step 4: Dispatch in `ingest_file`**

Replace `ingest_file` in `backend/src/policy_grapher/ingest.py`:

```python
from policy_grapher.models import DocumentIngestResult, DocumentRef, IngestResult
from policy_grapher.sources import is_document_source, pdf


def ingest_file(
    driver: Driver, database: str, filename: str, data_dir: Path
) -> IngestResult | DocumentIngestResult:
    path = resolve_csv_path(filename, data_dir)
    if not is_document_source(path):
        return ingest_parsed(driver, database, parse_corpus(path))

    extracted = pdf.extract_document(path)
    slug, nodes_created, relationships_created = ingest_document(driver, database, extracted)
    return DocumentIngestResult(
        format=extracted.report.format,
        document=DocumentRef(slug=slug, name=extracted.name),
        nodes_created=nodes_created,
        relationships_created=relationships_created,
        references_attributed=len(extracted.report.attributed),
        references_unattributed=list(extracted.report.unattributed),
        self_references_skipped=extracted.self_references_skipped,
    )
```

`resolve_csv_path` keeps its name and its traversal refusal; it resolves any bare filename, not only CSVs.

- [ ] **Step 5: Widen the route's response model**

In `backend/src/policy_grapher/routers/admin.py`, import `DocumentIngestResult` and `DocumentSourceError`, then change the route:

```python
@router.post("/ingest", response_model=IngestResult | DocumentIngestResult)
def ingest(
    body: IngestRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> IngestResult | DocumentIngestResult:
    try:
        return ingest_file(
            driver, settings.neo4j_database, body.filename, settings.data_dir
        )
    except (CsvSourceError, DocumentSourceError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
```

Expected: PASS, 7 tests.

- [ ] **Step 7: Run the whole suite**

```bash
cd backend && sg docker -c "uv run pytest -q"
```

Expected: everything passes. `test_corpus_e2e.py` and `test_ingest.py` read the manifest response by field name, so the added `source` field does not disturb them.

- [ ] **Step 8: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_pdf_ingest.py
git commit -m "feat: POST /ingest dispatches on extension and reports what it extracted"
```

---

## Task 11: Verify from a cold start, then sync the documentation

**Files:**
- Modify: `docs/specs/SPEC-001-di-1-policy-grapher.md`, `docs/specs/architecture.md`, `docs/backlog/backlog.md`, `docs/planning/roadmap.md`

- [ ] **Step 1: Run both suites and the container-free subset**

```bash
cd backend && sg docker -c "uv run pytest -q"
cd backend && uv run pytest -m "not integration" -q
sg docker -c "docker compose exec -T frontend npm test"
```

Expected: all green, output pristine. Frontend is unchanged by this story and must stay at 35.

- [ ] **Step 2: Verify against the running stack**

```bash
sg docker -c "docker compose down -v"
sg docker -c "docker compose up -d --build"
# wait for health, then:
curl -s -X POST localhost:5173/api/reset
curl -s -X POST localhost:5173/api/ingest -H 'Content-Type: application/json' \
     -d '{"filename":"500001p.pdf"}'
curl -s localhost:5173/api/documents/dodd-5000-01
```

Expected: the ingest returns `source: "document"`, and the document exists with its references. Put the verbatim output in the report.

- [ ] **Step 3: Update SPEC-001**

In the Input section, state that `POST /ingest` accepts a PDF issuance as well as a CSV manifest, and that a PDF yields one document. In the API Endpoints table, replace the `/ingest` row's description with both response shapes. Add a Testing bullet: extraction is scored against the corpus CSV, with per-document floors.

- [ ] **Step 4: Update `architecture.md`**

The Components row for the backend says `POST /ingest` parses the CSV. It now dispatches on extension. Add the `sources/` layout to the paragraph that describes `routers/`, and note in Known weak points that extraction is partial by design and that `references_unattributed` is the record of what was not captured.

- [ ] **Step 5: Update the backlog and roadmap**

Move STORY-016 to Done with sprint `3`. In `roadmap.md`'s Next section, the multi-format ingestion bullet now covers only DOCX and XLSX (STORY-035, STORY-036) — PDF has landed. Refresh both *Last reviewed* dates.

- [ ] **Step 6: Verify links resolve**

```bash
python3 /home/rhagan/.claude/skills/synced/project-docs-init/scripts/scaffold.py check --root .
```

Expected: no new broken links. Two pre-existing false positives in `superpowers/plans/` are expected — both are links inside fenced code blocks.

- [ ] **Step 7: Commit**

```bash
git add docs
git commit -m "docs: PDF ingestion is built; STORY-016 done"
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task.

| Design section | Task |
| --- | --- |
| Two source protocols, module layout | 1, 7 |
| `pypdf` text layer | 2 |
| Stage 1 format detection, stage 2 section location | 3 |
| Stage 3 entry splitting | 4 |
| Stage 4 identifier, stage 5 normalisation | 5 |
| Document identity from header | 6 |
| `ExtractedDocument`, `ExtractionReport`, failure handling | 7 |
| Ratchet floors | 8 |
| Merge layer, ADR-005 incremental slugs | 9 |
| Endpoint, discriminated response, one file per call | 10 |
| Idempotency | 9 (test), 11 (cold start) |
| Documentation | 11 |

**Placeholder scan.** No TBD, no "add error handling", no "similar to Task N". Task 8's `0.00` floors are the one intentional blank, and Step 1 of that task is the measurement that fills them — the spec deliberately refused to invent numbers the implementation would then have to hit.

**Type consistency.** `ExtractedDocument` and `ExtractionReport` field names are identical in Task 7's definition, Task 9's consumer and Task 10's response mapping. `ingest_document` returns `(slug, nodes_created, relationships_created)` in Task 9 and is unpacked in that order in Task 10. `locate_references` returns `(format, section | None)` in Task 3 and both elements are used accordingly in Tasks 4 and 7. `_ABBREVIATION` is defined once in Task 5 and reused by `document_name` in Task 6 — Task 6 must be implemented after Task 5, which the ordering enforces.

**Runtime semantics.**

- *Transaction boundaries.* `ingest_document` resolves every slug **before** opening the write transaction, because `allocate_slug` reads through `driver.execute_query` and cannot run inside the `session.execute_write` callback. The write itself is one transaction covering the document, its citations and its edges, so a failure part-way leaves nothing committed.
- *Relabelling hazard.* `MERGE_CITED` uses `ON CREATE SET` rather than `SET`. Plain `SET` would add `:External` to a corpus document that a later PDF happens to cite, silently demoting it.
- *Idempotency.* Re-ingesting depends on `allocate_slug` returning the same slug for the same name, which it does: it returns the bare slug when that slug is already taken by the same name. `MERGE` on `slug` then matches the existing node and counters report zero.
- *Self-reference ordering.* The self-reference count is computed after normalisation, since the document names itself in source form (`DoD Directive 5143.01`) and matches its own name only once both are normalised.
- *Sorted, de-duplicated references.* `extract_document` returns a sorted tuple over a set, so edge order is stable across runs — which matters because the acceptance check compares whole graph payloads.

**One known gap, stated rather than hidden.** Task 8's ratchet test passes the moment it is written, because its floors come from the parser it is measuring. It does not follow red-green and cannot: its purpose is to fail on the *next* regression, not this change. Task 8 Step 3 says so explicitly rather than dressing a green run up as a caught bug.
