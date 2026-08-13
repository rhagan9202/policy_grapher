# STORY-037 Source Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CSV re-ingest stops demoting a PDF-ingested document to `:External`, by making that label a maintained view of which ingests described a document rather than an opinion each ingest path sets for itself.

**Architecture:** An ingest becomes a `(:Source {id, kind, filename})` node; describing a document becomes a `(:Source)-[:DESCRIBES]->(:Document)` edge. `:External` is recomputed from one rule — no incoming `DESCRIBES` — by every path that touches a document. Ingest becomes uniformly additive: a document dropped from a later manifest keeps the edge from the earlier one.

**Tech Stack:** Python 3.14 · FastAPI · Pydantic v2 · neo4j driver v6 · pypdf · uv · pytest · testcontainers · ruff

**Decision:** [ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md), amending [ADR-002](../../specs/adr/ADR-002-external-references-and-corpus-first-graph.md). Follows [ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)'s typed-edge direction.

---

## Global Constraints

Copied from ADR-007 and verified against the running system on 2026-08-13. Every task's requirements implicitly include this section.

- **Python `>=3.14`**; **neo4j driver v6** — `driver.execute_query(...)` or `session.execute_write(fn, ...)` for multi-statement transactions. Never `session.run` at module level.
- **Labels and properties are exact:** `Document` with `slug` and `name`; extra label `External`; new label `Source` with `id`, `kind`, `filename`. `reference_role` was removed by ADR-006 and must not reappear.
- **Relationship types are exact:** `REFERENCES` (document → document) and the new `DESCRIBES` (source → document).
- **`kind` is `"manifest"`, `"document"` or `"api"`; `id` is `"<kind>:<filename>"`, except the api source whose id is the bare `"api"` (no filename).** A file re-ingested twice `MERGE`s the same `:Source`.
- **`POST /ingest` counters must keep counting only `Document` nodes and `REFERENCES` edges.** Source bookkeeping must not leak into `nodes_created` / `relationships_created`. The CSV must still report **438 / 672** on a clean graph, and a PDF of `500001p.pdf` still **16 / 15**.
- **`POST /reset` reports literal totals** and will change to **439 / 695** after one CSV ingest (438 documents + 1 source; 672 references + 23 describes). That is expected — update the test, do not scope the counters.
- **Ingest idempotency is a tested invariant.** Re-ingesting any file must still create nothing.
- **Baseline to preserve:** 182 backend tests, 35 frontend, all passing, output pristine. 99 backend tests run without Docker (`-m "not integration"`) and that must stay true.
- **Lint is a test.** `tests/test_lint.py` runs ruff over `backend/`.
- **Docker socket access needs `sg docker -c "..."`** on this machine. It must never appear in a committed file.
- Verified working on neo4j 2025.10: `EXISTS { (:Source)-[:DESCRIBES]->(d) }` as a `WHERE`/`RETURN` expression, and `MERGE` on `:Source` plus the edge being idempotent.

---

## File Structure

```
backend/src/policy_grapher/
  sources/provenance.py   NEW — Source/DESCRIBES Cypher and the label rule
  ingest.py               MODIFIED — both ingest paths record provenance, recompute the label
  documents.py            MODIFIED — POST /documents records the api source
  db.py                   MODIFIED — constraint on Source.id
backend/tests/
  test_provenance.py      NEW — the label rule and provenance queries
  test_ingest.py          MODIFIED — the transition test's demotion half changes
  test_reset.py           MODIFIED — counts become 439/695
  test_pdf_ingest.py      MODIFIED — + the regression this story exists to fix
  test_documents.py       MODIFIED — + a created document is described by the api
docs/
  specs/adr/ADR-007-...   status Proposed -> Accepted at the end
  specs/architecture.md   MODIFIED — data model, the :External rule
  specs/SPEC-001-...      MODIFIED — schema table, ingest additivity, reset counts
  backlog/backlog.md      MODIFIED — STORY-037 to Done
```

---

## Task 1: The provenance module and its constraint

**Files:**
- Create: `backend/src/policy_grapher/sources/provenance.py`, `backend/tests/test_provenance.py`
- Modify: `backend/src/policy_grapher/db.py`

**Interfaces:**
- Produces: `sources.provenance.source_id(kind: str, filename: str) -> str`; the Cypher constants `MERGE_SOURCE`, `DESCRIBES`, `REFRESH_EXTERNAL`; and `sources.provenance.MANIFEST` / `DOCUMENT` kind constants.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_provenance.py`:

```python
"""Provenance: which ingest described which document, and the :External view of it."""

import pytest
from neo4j import RoutingControl

from policy_grapher.sources import provenance

pytestmark = pytest.mark.integration


def labels_of(driver, database, slug: str) -> set[str]:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: $slug}) RETURN labels(d) AS labels",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return set(records[0]["labels"])


def make_document(driver, database, slug: str) -> None:
    driver.execute_query(
        "CREATE (d:Document {slug: $slug, name: $slug})",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.WRITE,
    )


def test_source_id_is_kind_and_filename():
    assert provenance.source_id(provenance.MANIFEST, "corpus.csv") == "manifest:corpus.csv"
    assert provenance.source_id(provenance.DOCUMENT, "500001p.pdf") == "document:500001p.pdf"


def test_a_described_document_loses_external_and_an_undescribed_one_gains_it(
    clean_graph, database
):
    make_document(clean_graph, database, "described")
    make_document(clean_graph, database, "cited-only")
    clean_graph.execute_query(
        provenance.MERGE_SOURCE,
        {"id": "manifest:x.csv", "kind": "manifest", "filename": "x.csv"},
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    clean_graph.execute_query(
        provenance.DESCRIBES,
        {"id": "manifest:x.csv", "slugs": ["described"]},
        database_=database,
        routing_=RoutingControl.WRITE,
    )

    clean_graph.execute_query(
        provenance.REFRESH_EXTERNAL,
        {"slugs": ["described", "cited-only"]},
        database_=database,
        routing_=RoutingControl.WRITE,
    )

    assert labels_of(clean_graph, database, "described") == {"Document"}
    assert labels_of(clean_graph, database, "cited-only") == {"Document", "External"}


def test_refreshing_is_idempotent(clean_graph, database):
    make_document(clean_graph, database, "cited-only")

    for _ in range(2):
        clean_graph.execute_query(
            provenance.REFRESH_EXTERNAL,
            {"slugs": ["cited-only"]},
            database_=database,
            routing_=RoutingControl.WRITE,
        )

    assert labels_of(clean_graph, database, "cited-only") == {"Document", "External"}


def test_recording_the_same_source_twice_creates_one_node(clean_graph, database):
    for _ in range(2):
        clean_graph.execute_query(
            provenance.MERGE_SOURCE,
            {"id": "document:a.pdf", "kind": "document", "filename": "a.pdf"},
            database_=database,
            routing_=RoutingControl.WRITE,
        )

    records, _, _ = clean_graph.execute_query(
        "MATCH (s:Source) RETURN count(s) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 1
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_provenance.py -v"
```

Expected: FAIL — `ImportError: cannot import name 'provenance'`.

- [ ] **Step 3: Write the module**

`backend/src/policy_grapher/sources/provenance.py`:

```python
"""Which ingest described which document, and the :External view derived from it.

ADR-007: a document is external when no ingest has described it first-hand. The
label is kept for query ergonomics — ADR-002 chose it and `WHERE NOT d:External`
stays cheap — but it is recomputed from this one rule rather than set by each
ingest path according to its own opinion.
"""

MANIFEST = "manifest"
DOCUMENT = "document"


def source_id(kind: str, filename: str) -> str:
    """The stable identity of an ingest source. Re-ingesting a file reuses it."""
    return f"{kind}:{filename}"


MERGE_SOURCE = """
MERGE (s:Source {id: $id})
SET s.kind = $kind, s.filename = $filename
"""

DESCRIBES = """
MATCH (s:Source {id: $id})
UNWIND $slugs AS slug
MATCH (d:Document {slug: slug})
MERGE (s)-[:DESCRIBES]->(d)
"""

# Applied to every slug an ingest touched, so a promotion and a demotion are the
# same statement rather than two passes that can disagree.
REFRESH_EXTERNAL = """
UNWIND $slugs AS slug
MATCH (d:Document {slug: slug})
FOREACH (_ IN CASE WHEN EXISTS { (:Source)-[:DESCRIBES]->(d) } THEN [1] ELSE [] END |
    REMOVE d:External)
FOREACH (_ IN CASE WHEN EXISTS { (:Source)-[:DESCRIBES]->(d) } THEN [] ELSE [1] END |
    SET d:External)
"""
```

- [ ] **Step 4: Add the uniqueness constraint**

In `backend/src/policy_grapher/db.py`, add a third entry to `CONSTRAINTS`:

```python
    (
        "CREATE CONSTRAINT source_id_unique IF NOT EXISTS "
        "FOR (s:Source) REQUIRE s.id IS UNIQUE"
    ),
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd backend && sg docker -c "uv run pytest tests/test_provenance.py tests/test_db.py -v"
```

Expected: PASS. `test_db.py` asserts the constraint set; if it pins a count, update it to three.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher/sources/provenance.py backend/src/policy_grapher/db.py backend/tests/test_provenance.py
git commit -m "feat: record which ingest described which document"
```

---

## Task 2: The manifest path records provenance

**Files:**
- Modify: `backend/src/policy_grapher/ingest.py`, `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `provenance.MERGE_SOURCE`, `DESCRIBES`, `REFRESH_EXTERNAL`, `source_id`, `MANIFEST`.
- Produces: `ingest.ingest_parsed(driver, database, parsed, filename: str)` — **a new required parameter**. `ingest_file` supplies `path.name`.

- [ ] **Step 1: Write the failing tests**

Replace the demotion half of `test_a_document_transitions_correctly_in_either_direction` in `backend/tests/test_ingest.py`. Keep the promotion half exactly as it is; change the two closing assertions and the docstring:

```python
def test_a_cited_only_document_becomes_described_but_is_never_undescribed(
    clean_graph, database, tmp_path
):
    """ADR-007: promotion still happens; demotion no longer does.

    A document dropped from a later manifest keeps the DESCRIBES edge the earlier
    one gave it, so it stays non-external. That is ingest being additive, which
    SPEC-001 already claimed it was — the old demotion was the one place it wasn't.
    """
    first = tmp_path / "first.csv"
    first.write_text(
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(first), first.name)

    def fetch(name: str) -> dict:
        records, _, _ = clean_graph.execute_query(
            "MATCH (d:Document {name: $name}) RETURN d:External AS is_external",
            {"name": name},
            database_=database,
            routing_=RoutingControl.READ,
        )
        return {"is_external": records[0]["is_external"]}

    assert fetch("A") == {"is_external": False}
    assert fetch("B") == {"is_external": True}

    second = tmp_path / "second.csv"
    second.write_text(
        'Document Name,References,Type\nB,"[\'A\']",Sub-Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(second), second.name)

    # B is now described: promotion, unchanged from before ADR-007.
    assert fetch("B") == {"is_external": False}
    # A is no longer a row in the current manifest, but first.csv still describes it.
    assert fetch("A") == {"is_external": False}


def test_a_manifest_records_itself_as_the_source_of_its_corpus_rows(
    clean_graph, database, tmp_path
):
    path = tmp_path / "corpus.csv"
    path.write_text(
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
        encoding="utf-8",
    )

    ingest_parsed(clean_graph, database, parse_corpus(path), path.name)

    records, _, _ = clean_graph.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document) "
        "RETURN s.id AS id, s.kind AS kind, collect(d.name) AS described",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "manifest:corpus.csv"
    assert records[0]["kind"] == "manifest"
    assert records[0]["described"] == ["A"]
```

Every other `ingest_parsed(...)` call in the suite needs its new `filename` argument — `test_ingest.py`, `test_graph.py` and any other caller. Pass the fixture's real filename.

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_ingest.py -v"
```

Expected: FAIL — `TypeError: ingest_parsed() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Thread the filename and record provenance**

In `backend/src/policy_grapher/ingest.py`, change the signature and the write:

```python
def ingest_parsed(
    driver: Driver, database: str, parsed: ParsedCorpus, filename: str
) -> IngestResult:
```

`MERGE_EXTERNAL` must **stop setting the label** — the refresh statement owns it now:

```python
MERGE_EXTERNAL = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name
"""
```

`MERGE_CORPUS` likewise drops its `REMOVE d:External`:

```python
MERGE_CORPUS = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
SET d.name = doc.name
"""
```

Delete the comment above the statement loop that explains the bidirectional flip — it describes behaviour ADR-007 removed. Replace it with a line saying the label is refreshed at the end, from provenance.

Inside `_write_ingest`, after the node and edge statements, record the source and refresh the label. **Do not add their counters to the returned totals** — `nodes_created` and `relationships_created` report documents and references, per the Global Constraints:

```python
    tx.run(
        MERGE_SOURCE,
        {"id": source_id(MANIFEST, filename), "kind": MANIFEST, "filename": filename},
    ).consume()
    tx.run(
        DESCRIBES,
        {"id": source_id(MANIFEST, filename), "slugs": [d["slug"] for d in corpus_docs]},
    ).consume()
    tx.run(
        REFRESH_EXTERNAL,
        {"slugs": [d["slug"] for d in corpus_docs + external_docs]},
    ).consume()
```

`_write_ingest` needs `filename` passed through from `ingest_parsed`.

- [ ] **Step 4: Update `ingest_file` to supply the name**

```python
    return ingest_parsed(driver, database, parse_corpus(path), path.name)
```

- [ ] **Step 5: Run the tests, then the whole suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_ingest.py tests/test_graph.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: the ingest and graph tests pass. `test_reset.py` now fails on counts — that is Task 5. Nothing else should fail; if `test_corpus_e2e.py` does, the counters leaked source bookkeeping and Step 3 is wrong.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher/ingest.py backend/tests
git commit -m "feat: a manifest records itself as the source of its corpus rows"
```

---

## Task 3: The document path records provenance, and the bug is fixed

**Files:**
- Modify: `backend/src/policy_grapher/ingest.py`, `backend/tests/test_pdf_ingest.py`

**Interfaces:**
- Produces: `ingest.ingest_document(driver, database, extracted, filename: str)` — **a new required parameter**.

- [ ] **Step 1: Write the failing test — this is the story's whole point**

Append to `backend/tests/test_pdf_ingest.py`:

```python
def test_a_csv_reingest_does_not_demote_a_pdf_ingested_document(client_with_graph):
    """STORY-037. The corpus CSV lists DoDD 5000.01 as an external reference of other
    documents. Before ADR-007 that demoted the PDF-ingested node to :External, hiding
    it from the default graph view."""
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    client_with_graph.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )

    body = client_with_graph.get("/documents/dodd-5000-01").json()
    assert body["is_external"] is False

    graph = client_with_graph.get("/graph").json()
    assert "dodd-5000-01" in {node["id"] for node in graph["nodes"]}


def test_a_pdf_records_itself_as_the_source_of_its_document(client_with_graph, driver, database):
    from neo4j import RoutingControl

    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    records, _, _ = driver.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document {slug: 'dodd-5000-01'}) "
        "RETURN s.id AS id, s.kind AS kind",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "document:500001p.pdf"
    assert records[0]["kind"] == "document"


def test_a_cited_document_a_pdf_introduces_is_still_external(client_with_graph):
    """Only the PDF's own subject is described; what it cites is not."""
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    body = client_with_graph.get("/documents/dodd-1322-18").json()
    assert body["is_external"] is True
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
```

Expected: `test_a_csv_reingest_does_not_demote_a_pdf_ingested_document` fails with `is_external` true — the defect, reproduced. The other two fail on the missing source.

- [ ] **Step 3: Record provenance in the document path**

In `ingest_document`, add the `filename` parameter and, inside `_write_document`, do the same three statements as Task 2 — with `DOCUMENT` as the kind, the single document's slug as what is described, and the document plus its citations as the slugs to refresh. `MERGE_DOCUMENT` drops its `REMOVE d:External` and `MERGE_CITED` drops its `d:External`; the refresh owns the label:

```python
MERGE_DOCUMENT = """
MERGE (d:Document {slug: $slug})
SET d.name = $name
"""

MERGE_CITED = """
UNWIND $docs AS doc
MERGE (d:Document {slug: doc.slug})
ON CREATE SET d.name = doc.name
"""
```

Keep `ON CREATE SET` on `MERGE_CITED`: it must not overwrite the name of a document that already exists.

- [ ] **Step 4: Update the caller**

In `ingest_file`'s document branch:

```python
    slug, nodes_created, relationships_created = ingest_document(
        driver, database, extracted, path.name
    )
```

- [ ] **Step 5: Run the tests, then the whole suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_pdf_ingest.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: the PDF tests pass. Only `test_reset.py` should still fail, on counts — Task 5 fixes it.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher/ingest.py backend/tests/test_pdf_ingest.py
git commit -m "fix: a CSV re-ingest no longer demotes a PDF-ingested document"
```

---

## Task 4: `POST /documents` records the API as its source

Without this the drift guard in Task 5 is false the moment anyone creates a document by hand: after ADR-006 that endpoint supplies only a name, so the node has no provenance and would evaluate as external — invisible in the default graph view moments after a user created it.

**Files:**
- Modify: `backend/src/policy_grapher/documents.py`, `backend/tests/test_documents.py`

**Interfaces:**
- Consumes: `provenance.MERGE_SOURCE`, `DESCRIBES`, `REFRESH_EXTERNAL`, `source_id`, and a new `provenance.API` kind constant.
- Produces: no signature change — `create_document(driver, database, name)` keeps its shape.

- [ ] **Step 1: Add the `API` kind**

In `backend/src/policy_grapher/sources/provenance.py`, alongside `MANIFEST` and `DOCUMENT`:

```python
API = "api"
API_SOURCE_ID = "api"
```

`API_SOURCE_ID` is a bare `"api"` rather than `source_id(API, ...)` because there is no filename — one node stands for every hand-created document, per ADR-007.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_documents.py`:

```python
def test_a_created_document_is_described_by_the_api(client_with_graph, driver, database):
    """ADR-007: a user asserting a document exists is provenance."""
    from neo4j import RoutingControl

    created = client_with_graph.post("/documents", json={"name": "Hand Made Doc"}).json()

    records, _, _ = driver.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document {slug: $slug}) RETURN s.id AS id, s.kind AS kind",
        {"slug": created["slug"]},
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "api"
    assert records[0]["kind"] == "api"


def test_a_created_document_is_not_external(client_with_graph):
    created = client_with_graph.post("/documents", json={"name": "Hand Made Doc"}).json()

    assert created["is_external"] is False
    assert client_with_graph.get(f"/documents/{created['slug']}").json()["is_external"] is False


def test_every_created_document_shares_one_api_source(client_with_graph, driver, database):
    from neo4j import RoutingControl

    client_with_graph.post("/documents", json={"name": "First Hand Made"})
    client_with_graph.post("/documents", json={"name": "Second Hand Made"})

    records, _, _ = driver.execute_query(
        "MATCH (s:Source {kind: 'api'}) RETURN count(s) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 1
```

- [ ] **Step 3: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
```

Expected: the first and third fail on a missing `:Source`. The second may pass already — `CREATE` adds no `:External` label today — but it becomes load-bearing once the refresh runs, so keep it.

- [ ] **Step 4: Record provenance on create**

In `create_document`, after `_write(driver, database, CREATE_DOCUMENT, ...)` and before returning, record the API source and refresh the label for the new slug. Use the existing `_write` helper for each statement, passing `{"id": API_SOURCE_ID, "kind": API, "filename": ""}`, then `{"id": API_SOURCE_ID, "slugs": [slug]}`, then `{"slugs": [slug]}`.

- [ ] **Step 5: Run the tests, then the whole suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: the document tests pass. Only `test_reset.py` should still fail, on counts — Task 5 fixes it.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_documents.py
git commit -m "feat: a document created through the API is described by the API"
```

---

## Task 5: Reset counts, and a guard against label drift

**Files:**
- Modify: `backend/tests/test_reset.py`
- Modify: `backend/tests/test_provenance.py`

- [ ] **Step 1: Update the reset expectations**

`POST /reset` reports literal totals from `MATCH (n) DETACH DELETE n`. After one CSV ingest the graph holds 438 documents plus 1 source, and 672 references plus 23 describes:

```python
    assert response.json() == {"nodes_deleted": 439, "relationships_deleted": 695}
```

Add a comment naming what the extra 1 and 23 are, so the next person does not read it as drift.

- [ ] **Step 2: Add the drift guard**

The label is derived but stored, so a future write path could forget to refresh it. Append to `backend/tests/test_provenance.py`:

```python
SAMPLE = "dod_policy_references_08122026.csv"


def test_no_document_disagrees_with_its_provenance(client_with_graph, driver, database):
    """:External is a view. If a write path forgets to refresh it, this is what says so."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})

    records, _, _ = driver.execute_query(
        "MATCH (d:Document) "
        "WITH d, EXISTS { (:Source)-[:DESCRIBES]->(d) } AS described "
        "WHERE described = d:External "
        "RETURN collect(d.slug)[..10] AS wrong, count(*) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 0, records[0]["wrong"]
```

- [ ] **Step 3: Run the whole suite**

```bash
cd backend && sg docker -c "uv run pytest -q"
cd backend && uv run pytest -m "not integration" -q
```

Expected: everything passes. The container-free count rises by one (`test_source_id_is_kind_and_filename`).

- [ ] **Step 4: Commit**

```bash
git add backend/tests
git commit -m "test: reset counts include provenance, and :External cannot drift unnoticed"
```

---

## Task 6: Verify from a cold start, then sync the documentation

**Files:**
- Modify: `docs/specs/adr/ADR-007-sources-describe-documents.md`, `docs/specs/architecture.md`, `docs/specs/SPEC-001-di-1-policy-grapher.md`, `docs/backlog/backlog.md`

- [ ] **Step 1: Run both suites**

```bash
cd backend && sg docker -c "uv run pytest -q"
sg docker -c "docker compose exec -T frontend npm test"
```

Expected: backend green, frontend unchanged at **35** — this story touches no frontend code.

- [ ] **Step 2: Verify against a live stack**

```bash
sg docker -c "docker compose down -v"
sg docker -c "docker compose up -d --build"
# wait for health, then:
curl -s -X POST localhost:5173/api/reset
curl -s -X POST localhost:5173/api/ingest -H 'Content-Type: application/json' -d '{"filename":"500001p.pdf"}'
curl -s -X POST localhost:5173/api/ingest -H 'Content-Type: application/json' \
     -d '{"filename":"dod_policy_references_08122026.csv"}'
curl -s localhost:5173/api/documents/dodd-5000-01
curl -s -X POST localhost:5173/api/query -H 'Content-Type: application/json' \
     -d '{"cypher":"MATCH (s:Source)-[:DESCRIBES]->(d) RETURN s.id AS source, count(d) AS described ORDER BY source"}'
```

Expected: `dodd-5000-01` has `is_external: false` after the CSV ingest, and the query shows two sources — `document:500001p.pdf` describing 1 and `manifest:dod_policy_references_08122026.csv` describing 23. Put the verbatim output in the report.

- [ ] **Step 3: Accept the ADR**

Change ADR-007's status line from `Proposed` to `Accepted`. Change nothing else — it is a frozen record from that point.

- [ ] **Step 4: Update `architecture.md`**

In the data model, add `Source` to the node table and `DESCRIBES` to the relationship table. Replace the `:External` explanation with the rule: a document is external when no source describes it, recomputed by every ingest. State that ingest is now uniformly additive — a document dropped from a later manifest keeps its earlier provenance — and that `POST /reset` is how to make the graph match a changed file. Link ADR-007.

- [ ] **Step 5: Update SPEC-001**

Node and relationship tables gain `Source` and `DESCRIBES`. The "Ingest is additive" bullet is now true without exception — say so, and note that the label follows provenance. Correct the `POST /reset` description if it quotes counts.

- [ ] **Step 6: Move STORY-037 to Done**

Sprint `3`, alongside STORY-016, STORY-033 and STORY-034. Refresh *Last reviewed*.

- [ ] **Step 7: Verify links resolve**

```bash
python3 /home/rhagan/.claude/skills/synced/project-docs-init/scripts/scaffold.py check --root .
```

Expected: no new broken links. Two pre-existing false positives in `superpowers/plans/` are expected — both are links inside fenced code blocks.

- [ ] **Step 8: Commit**

```bash
git add docs
git commit -m "docs: ADR-007 accepted; :External follows provenance; STORY-037 done"
```

---

## Self-Review

**Decision coverage.** Every numbered decision in ADR-007 maps to a task.

| ADR-007 decision | Task |
| --- | --- |
| 1 — an ingest is a `:Source` node | 1, 2, 3 |
| 2 — describing is a `DESCRIBES` edge | 1, 2, 3 |
| 3 — `:External` is a maintained view from one rule | 1 (the rule), 2, 3 and 4 (applied), 5 (drift guard) |
| 5 — ingest becomes uniformly additive | 2 (the changed test), 6 (the documentation) |
| Decision 4 — the API is a source | 4 |
| Consequence — reset counts change | 5 |
| Consequence — counters exclude provenance | 2, 3 (explicit in both) |
| Consequence — existing graphs need a reset | 6 Step 2 starts from `down -v` |

**Placeholder scan.** No TBD, no "add error handling", no "similar to Task N". Task 6's documentation steps describe what must become true rather than quoting replacement prose, because the surrounding text will have moved by then; every code step carries real code.

**Type consistency.** `ingest_parsed` and `ingest_document` both gain a trailing `filename: str`, supplied by `ingest_file` as `path.name` in Task 2 Step 4 and Task 3 Step 4. `source_id(kind, filename)` is defined in Task 1 and called in Tasks 2 and 3 with the `MANIFEST` / `DOCUMENT` constants from the same module. `REFRESH_EXTERNAL` takes `{"slugs": [...]}` in all three call sites.

**Runtime semantics.**

- *Transaction boundaries.* The provenance statements run inside the existing `session.execute_write` callbacks, so a failure recording provenance rolls back the documents and edges with it. There is no window where a document exists without the label its provenance implies.
- *Counter discipline.* `_write_ingest` and `_write_document` sum `summary.counters` per statement. The three provenance statements are consumed but never added, which is what keeps the CSV reporting 438/672 and a PDF 16/15. This is the single easiest thing to get wrong in the whole plan, and `test_corpus_e2e.py` is what catches it.
- *Order within the transaction.* `DESCRIBES` must run before `REFRESH_EXTERNAL`, or the refresh reads provenance that is not there yet and marks everything external.
- *Idempotency.* `MERGE` on `:Source {id}` and on the `DESCRIBES` edge creates nothing on a second ingest; `REFRESH_EXTERNAL` is a set/remove to a fixed target and so is naturally idempotent. Verified against neo4j 2025.10 before this plan was written.
- *The refresh's slug scope.* Both paths refresh every slug they touched, not only the ones they described. A cited-only name must be able to *gain* the label on first sight, and a previously-cited document must be able to lose it when a later ingest describes it.

**A hole found while writing this plan, and closed rather than deferred.** `POST /documents` creates a `Document` outside either ingest path. Probed against the running system, it returns `is_external: false` today because `CREATE` simply adds no label. Under ADR-007's rule that node has no provenance and *should* be external — so the drift guard would have failed against any graph where somebody had created a document by hand, and a user would have watched a document they just created vanish from the default view. Task 4 closes it by treating the user's assertion as a source. The remaining judgement — whether `api` should become per-user once authentication exists — is named in ADR-007 as a later decision rather than left implicit.

**One real gap remains.** The drift guard runs after the ingests the test performs; it cannot prove the invariant for a write path nobody has written yet. That is a limit of testing, not of the design: the rule now lives in one statement, so a new path either calls it or is visibly wrong in review.
