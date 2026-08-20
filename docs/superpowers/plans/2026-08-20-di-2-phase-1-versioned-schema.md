# DI-2 Phase 1: Versioned Schema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the graph a way to say "this instrument has editions, and this one supersedes that one" — the prerequisite for detecting that a policy changed at all.

**Architecture:** `:Document` stays exactly as it is and becomes the *instrument identity*. Editions hang off it as `:DocumentVersion` nodes joined by `HAS_VERSION`, chained by `SUPERSEDES`. `:Authority` and `:Entity` arrive as reference nodes. Every DI-1 invariant and test survives untouched.

**Tech Stack:** FastAPI, Pydantic v2, neo4j Python driver 6.x, pytest + testcontainers.

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Ontology* and *Ingestion and versioning*.

**Depends on:** Phase 0 (merged). Every route requires a principal, so integration tests use the `client_with_auth` fixture.

## Global Constraints

- Python `>=3.14`; dependencies via `uv`. Add nothing to `pyproject.toml`.
- Ruff is enforced **as a test** (`backend/tests/test_lint.py`). A lint failure is a test failure.
- Integration tests run against a real `neo4j:2025.10` via testcontainers. **Never mock the driver.**
- Relationship types are directed `SCREAMING_SNAKE_CASE` verb phrases read source → target ([ADR-006](../../specs/adr/ADR-006-relational-facts-live-on-typed-edges.md)).
- Ingest stays **uniformly additive** ([ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md)). Nothing demotes or un-describes; `POST /reset` is still the only subtractive path.
- Re-ingesting an identical file remains a no-op. This is a tested DI-1 invariant and must not regress.
- IDs are permanent. Never renumber a STORY or ADR.
- Documentation updated in the same change.

## Decisions an executor must not silently change

**1. Versions come only from the single-document path.** `sources/manifest.py` parses a CSV of citations — no text, no dates, no editions. It keeps creating bare `:Document` nodes exactly as today. Only `sources/pdf.py`'s path creates a `:DocumentVersion`, because only it has a file to checksum and a cover page to date. Adding versions to the manifest path would invent editions that do not exist.

**2. `effective_date` is optional.** Not every issuance states one legibly, and guessing is worse than absent. Ordering falls back to `ingested_at` when a date is missing, and the API reports which basis was used so a reader is never misled about it.

**3. Version identity is deterministic, like slugs.** `version_id = f"{document_slug}@{effective_date or checksum[:12]}"`. Re-ingesting the same file resolves to the same id and is a no-op. This mirrors [ADR-003](../../specs/adr/ADR-003-slug-identifiers.md)'s reasoning — identity is a function of content, not of ingest order.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/db.py` | *Modify* — four new constraints |
| `backend/src/policy_grapher/versions.py` | *Create* — version identity, creation, supersession |
| `backend/src/policy_grapher/models.py` | *Modify* — `DocumentVersionOut`, extend `DocumentOut` |
| `backend/src/policy_grapher/ingest.py` | *Modify* — the PDF path writes a version |
| `backend/src/policy_grapher/sources/pdf.py` | *Modify* — extract an effective date when the cover page states one |
| `backend/src/policy_grapher/routers/documents.py` | *Modify* — `GET /documents/{slug}/versions` |
| `backend/tests/test_versions.py` | *Create* |
| `docs/specs/adr/ADR-011-*.md` | *Create* — instruments have versions; `:Document` is identity |

---

### Task 1: `:DocumentVersion` and `HAS_VERSION`

**Files:**
- Create: `backend/src/policy_grapher/versions.py`, `backend/tests/test_versions.py`
- Modify: `backend/src/policy_grapher/db.py`, `backend/src/policy_grapher/models.py`

**Interfaces:**
- Consumes: `Driver` from neo4j; the existing `:Document {slug, name}` node
- Produces: `version_id(document_slug: str, effective_date: date | None, checksum: str) -> str`, `merge_version(tx, *, document_slug, effective_date, checksum, source_uri) -> str` (returns the resolved `version_id`), and `DocumentVersionOut`

- [ ] **Step 1: Write the failing identity tests**

Create `backend/tests/test_versions.py`:

```python
from datetime import date

from policy_grapher.versions import version_id


def test_identity_prefers_the_effective_date():
    assert version_id("dodi-5000-88", date(2026, 4, 1), "abc123def456") == "dodi-5000-88@2026-04-01"


def test_identity_falls_back_to_a_checksum_prefix_when_undated():
    assert version_id("dodi-5000-88", None, "abc123def456789") == "dodi-5000-88@abc123def456"


def test_identity_is_stable_for_the_same_inputs():
    """Re-ingesting the same file must resolve to the same version, not a new one."""
    first = version_id("d", None, "abc123def456789")
    second = version_id("d", None, "abc123def456789")
    assert first == second


def test_two_editions_of_one_instrument_get_different_identities():
    a = version_id("d", date(2024, 1, 1), "aaa")
    b = version_id("d", date(2026, 1, 1), "bbb")
    assert a != b
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_versions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'policy_grapher.versions'`

- [ ] **Step 3: Write the identity function**

Create `backend/src/policy_grapher/versions.py`:

```python
"""Editions of an instrument.

`:Document` is the instrument's stable identity — unique slug, unique name,
provenance-tracked. A `:DocumentVersion` is one edition of it. Identity is a
function of content, not of ingest order, for the same reason slugs are
(ADR-003): re-ingesting a file must resolve to the version it already made.
"""

from datetime import date

from neo4j import ManagedTransaction

CHECKSUM_PREFIX = 12

MERGE_VERSION = """
MATCH (d:Document {slug: $document_slug})
MERGE (v:DocumentVersion {version_id: $version_id})
ON CREATE SET v.effective_date = $effective_date,
              v.checksum       = $checksum,
              v.source_uri     = $source_uri,
              v.ingested_at    = datetime()
MERGE (d)-[:HAS_VERSION]->(v)
RETURN v.ingested_at = v.ingested_at AS existed
"""


def version_id(document_slug: str, effective_date: date | None, checksum: str) -> str:
    """A version's permanent identity.

    Dated editions are addressed by their date, which is what a reader cites.
    An undated one falls back to a checksum prefix — stable, meaningless to a
    human, and honest about the fact that we could not read a date.
    """
    discriminator = (
        effective_date.isoformat() if effective_date else checksum[:CHECKSUM_PREFIX]
    )
    return f"{document_slug}@{discriminator}"
```

- [ ] **Step 4: Run the identity tests**

Run: `cd backend && uv run pytest tests/test_versions.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add the constraint**

In `backend/src/policy_grapher/db.py`, append to `CONSTRAINTS`:

```python
    (
        "CREATE CONSTRAINT document_version_id_unique IF NOT EXISTS "
        "FOR (v:DocumentVersion) REQUIRE v.version_id IS UNIQUE"
    ),
```

- [ ] **Step 6: Write the failing graph test**

Append to `backend/tests/test_versions.py`:

```python
import pytest

from policy_grapher.versions import merge_version


@pytest.mark.integration
def test_a_version_attaches_to_its_document(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )

    with clean_graph.session(database=database) as session:
        resolved = session.execute_write(
            merge_version,
            document_slug="d",
            effective_date=date(2026, 4, 1),
            checksum="abc",
            source_uri="file:///d.pdf",
        )

    assert resolved == "d@2026-04-01"
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Document {slug: 'd'})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        database_=database,
    )
    assert [r["id"] for r in records] == ["d@2026-04-01"]


@pytest.mark.integration
def test_re_merging_the_same_version_creates_nothing(clean_graph, database):
    """The DI-1 idempotency invariant, extended to versions."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    kwargs = dict(
        document_slug="d", effective_date=None, checksum="abc", source_uri="file:///d.pdf"
    )

    with clean_graph.session(database=database) as session:
        first = session.execute_write(merge_version, **kwargs)
        second = session.execute_write(merge_version, **kwargs)

    # Same identity both times — the second call resolved to the first's version.
    assert first == second
    records, _, _ = clean_graph.execute_query(
        "MATCH (v:DocumentVersion) RETURN count(v) AS total", database_=database
    )
    assert records[0]["total"] == 1
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_versions.py -m integration -v`
Expected: FAIL — `ImportError: cannot import name 'merge_version'`

- [ ] **Step 8: Implement `merge_version`**

Append to `backend/src/policy_grapher/versions.py`:

```python
def merge_version(
    tx: ManagedTransaction,
    *,
    document_slug: str,
    effective_date: date | None,
    checksum: str,
    source_uri: str,
) -> str:
    """Attach an edition to its instrument. Returns the resolved version id.

    Returns the id rather than a created/not-created flag because every caller
    needs the id — phase 2 chunks against it, phase 3 extracts against it. A
    boolean would force each of them to recompute it.

    Additive per ADR-007: an existing version is left exactly as it was, so a
    re-ingest cannot rewrite the date or checksum of an edition already recorded.
    """
    resolved = version_id(document_slug, effective_date, checksum)
    tx.run(
        MERGE_VERSION,
        {
            "document_slug": document_slug,
            "version_id": resolved,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "checksum": checksum,
            "source_uri": source_uri,
        },
    ).consume()
    return resolved
```

- [ ] **Step 9: Add the response model**

In `backend/src/policy_grapher/models.py`, after `DocumentOut`:

```python
class DocumentVersionOut(BaseModel):
    version_id: str
    effective_date: str | None
    checksum: str
    source_uri: str
    supersedes: str | None
```

- [ ] **Step 10: Run the full suite and commit**

Run: `cd backend && uv run pytest`
Expected: PASS — the existing 227 plus the new ones.

```bash
git add backend/src/policy_grapher/versions.py backend/src/policy_grapher/db.py \
        backend/src/policy_grapher/models.py backend/tests/test_versions.py
git commit -m "feat: instruments have versions"
```

---

### Task 2: `SUPERSEDES`

**Files:**
- Modify: `backend/src/policy_grapher/versions.py`, `backend/tests/test_versions.py`

**Interfaces:**
- Consumes: `merge_version` from Task 1
- Produces: `link_supersession(tx, document_slug) -> int` — rebuilds the chain for one instrument, returns the number of edges now in it

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_versions.py`:

```python
from policy_grapher.versions import link_supersession


def _add(driver, database, slug, effective_date, checksum):
    with driver.session(database=database) as session:
        session.execute_write(
            merge_version,
            document_slug=slug,
            effective_date=effective_date,
            checksum=checksum,
            source_uri=f"file:///{checksum}.pdf",
        )


@pytest.mark.integration
def test_a_newer_edition_supersedes_the_older_one(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2024, 1, 1), "old")
    _add(clean_graph, database, "d", date(2026, 1, 1), "new")

    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [("d@2026-01-01", "d@2024-01-01")]


@pytest.mark.integration
def test_the_chain_is_rebuilt_not_appended(clean_graph, database):
    """An edition ingested out of order must not leave a wrong chain behind."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2024, 1, 1), "a")
    _add(clean_graph, database, "d", date(2026, 1, 1), "c")
    with clean_graph.session(database=database) as session:
        session.execute_write(link_supersession, "d")

    # The 2025 edition arrives last but belongs in the middle.
    _add(clean_graph, database, "d", date(2025, 1, 1), "b")
    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 2
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older "
        "ORDER BY newer.version_id",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [
        ("d@2025-01-01", "d@2024-01-01"),
        ("d@2026-01-01", "d@2025-01-01"),
    ]


@pytest.mark.integration
def test_a_single_edition_has_no_supersession(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2026, 1, 1), "only")

    with clean_graph.session(database=database) as session:
        assert session.execute_write(link_supersession, "d") == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/test_versions.py -m integration -k supersed -v`
Expected: FAIL — `ImportError: cannot import name 'link_supersession'`

- [ ] **Step 3: Implement it**

Append to `backend/src/policy_grapher/versions.py`:

```python
REBUILD_SUPERSESSION = """
MATCH (d:Document {slug: $document_slug})-[:HAS_VERSION]->(v:DocumentVersion)
WITH v ORDER BY coalesce(v.effective_date, '') ASC, v.ingested_at ASC
WITH collect(v) AS ordered
CALL {
    WITH ordered
    UNWIND range(0, size(ordered) - 1) AS i
    WITH ordered[i] AS v
    MATCH (v)-[old:SUPERSEDES]->()
    DELETE old
}
WITH ordered
UNWIND range(1, size(ordered) - 1) AS i
WITH ordered[i] AS newer, ordered[i - 1] AS older
MERGE (newer)-[:SUPERSEDES]->(older)
RETURN count(*) AS edges
"""


def link_supersession(tx: ManagedTransaction, document_slug: str) -> int:
    """Rebuild one instrument's supersession chain from scratch.

    Rebuilt rather than appended because editions do not arrive in order. A
    2025 edition ingested after the 2026 one belongs in the middle, and an
    append-only chain would record that 2026 supersedes 2024 forever.

    This deletes and recreates SUPERSEDES edges, which is the one place ingest
    is not purely additive. It is safe because the chain is *derived* from the
    versions' own dates — no human decision lives on these edges. Do not extend
    this pattern to edges that carry a judgement.
    """
    records = tx.run(REBUILD_SUPERSESSION, {"document_slug": document_slug})
    row = records.single()
    return row["edges"] if row else 0
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/test_versions.py -m integration -v`
Expected: PASS

- [ ] **Step 5: Run the full suite and commit**

Run: `cd backend && uv run pytest`
Expected: PASS

```bash
git add backend/src/policy_grapher/versions.py backend/tests/test_versions.py
git commit -m "feat: a newer edition supersedes the one before it"
```

---

### Task 3: `:Authority` and `:Entity`

**Files:**
- Modify: `backend/src/policy_grapher/versions.py`, `backend/src/policy_grapher/db.py`, `backend/tests/test_versions.py`

**Interfaces:**
- Produces: `merge_authority(tx, *, slug, name) -> None`, `attach_authority(tx, *, version_id, authority_slug) -> None`, `merge_entity(tx, *, slug, name, kind) -> None`

These are reference nodes with no behaviour of their own yet — Phase 3's extraction attaches obligations to them. They exist now so the schema is complete before anything depends on it.

- [ ] **Step 1: Add the constraints**

In `backend/src/policy_grapher/db.py`, append to `CONSTRAINTS`:

```python
    (
        "CREATE CONSTRAINT authority_slug_unique IF NOT EXISTS "
        "FOR (a:Authority) REQUIRE a.slug IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT entity_slug_unique IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.slug IS UNIQUE"
    ),
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_versions.py`:

```python
from policy_grapher.versions import attach_authority, merge_authority, merge_entity


@pytest.mark.integration
def test_an_authority_issues_a_version(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2026, 1, 1), "x")

    with clean_graph.session(database=database) as session:
        session.execute_write(merge_authority, slug="usd-c", name="Under Secretary of Defense (Comptroller)")
        session.execute_write(attach_authority, version_id="d@2026-01-01", authority_slug="usd-c")

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'd@2026-01-01'})-[:ISSUED_BY]->(a:Authority) "
        "RETURN a.name AS name",
        database_=database,
    )
    assert [r["name"] for r in records] == ["Under Secretary of Defense (Comptroller)"]


@pytest.mark.integration
def test_reference_nodes_are_idempotent(clean_graph, database):
    with clean_graph.session(database=database) as session:
        for _ in range(2):
            session.execute_write(merge_authority, slug="dla", name="Defense Logistics Agency")
            session.execute_write(merge_entity, slug="dla-j8", name="DLA J8", kind="directorate")

    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Authority) WITH count(a) AS authorities "
        "MATCH (e:Entity) RETURN authorities, count(e) AS entities",
        database_=database,
    )
    assert (records[0]["authorities"], records[0]["entities"]) == (1, 1)
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_versions.py -m integration -k "authority or reference" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 4: Implement**

Append to `backend/src/policy_grapher/versions.py`:

```python
MERGE_AUTHORITY = """
MERGE (a:Authority {slug: $slug})
ON CREATE SET a.name = $name
"""

ATTACH_AUTHORITY = """
MATCH (v:DocumentVersion {version_id: $version_id})
MATCH (a:Authority {slug: $authority_slug})
MERGE (v)-[:ISSUED_BY]->(a)
"""

MERGE_ENTITY = """
MERGE (e:Entity {slug: $slug})
ON CREATE SET e.name = $name, e.kind = $kind
"""


def merge_authority(tx: ManagedTransaction, *, slug: str, name: str) -> None:
    tx.run(MERGE_AUTHORITY, {"slug": slug, "name": name}).consume()


def attach_authority(tx: ManagedTransaction, *, version_id: str, authority_slug: str) -> None:
    tx.run(
        ATTACH_AUTHORITY, {"version_id": version_id, "authority_slug": authority_slug}
    ).consume()


def merge_entity(tx: ManagedTransaction, *, slug: str, name: str, kind: str) -> None:
    tx.run(MERGE_ENTITY, {"slug": slug, "name": name, "kind": kind}).consume()
```

`ON CREATE SET` rather than `SET`: a re-ingest must not silently rewrite an
authority's name, for the same reason ADR-007 made ingest additive.

- [ ] **Step 5: Run tests, full suite, commit**

Run: `cd backend && uv run pytest`
Expected: PASS

```bash
git add backend/src/policy_grapher/versions.py backend/src/policy_grapher/db.py \
        backend/tests/test_versions.py
git commit -m "feat: authorities issue versions, entities exist to be bound"
```

---

### Task 4: Wire versions into ingest and the API

**Files:**
- Modify: `backend/src/policy_grapher/ingest.py`, `backend/src/policy_grapher/sources/pdf.py`, `backend/src/policy_grapher/routers/documents.py`, `backend/src/policy_grapher/models.py`
- Modify: `backend/tests/test_pdf_ingest.py`, `backend/tests/test_versions.py`
- Create: `docs/specs/adr/ADR-011-instruments-have-versions.md`

**Interfaces:**
- Consumes: everything from Tasks 1–3
- Produces: `GET /documents/{slug}/versions -> list[DocumentVersionOut]`

- [ ] **Step 1: Write the failing end-to-end test**

Append to `backend/tests/test_versions.py`:

```python
@pytest.mark.integration
def test_ingesting_a_pdf_records_a_version(client_with_auth, tmp_path):
    """The single-document path versions; the manifest path does not."""
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    assert response.status_code == 200
    slug = response.json()["document"]["slug"]

    versions = client_with_auth.get(f"/documents/{slug}/versions")
    assert versions.status_code == 200
    body = versions.json()
    assert len(body) == 1
    assert body[0]["checksum"]
    assert body[0]["supersedes"] is None


@pytest.mark.integration
def test_re_ingesting_the_same_pdf_adds_no_version(client_with_auth):
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = first.json()["document"]["slug"]
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    versions = client_with_auth.get(f"/documents/{slug}/versions").json()
    assert len(versions) == 1


@pytest.mark.integration
def test_the_manifest_path_creates_no_versions(client_with_auth):
    """A CSV of citations describes no edition — inventing one would be a lie."""
    client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )
    documents = client_with_auth.get("/documents").json()
    assert documents  # sanity: the corpus loaded

    versions = client_with_auth.get(f"/documents/{documents[0]['slug']}/versions").json()
    assert versions == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_versions.py -m integration -k ingest -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Extract an effective date from the PDF**

In `backend/src/policy_grapher/sources/pdf.py`, add a stage that reads a date from the
cover page and returns `None` when it cannot. DoD issuances state it near the designator,
in forms such as `April 1, 2026` and `1 April 2026`:

```python
DATE_PATTERNS = (
    re.compile(r"\b(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b"),
    re.compile(r"\b(?P<day>\d{1,2})\s+(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+(?P<year>\d{4})\b"),
)


def effective_date(cover_text: str) -> date | None:
    """The date the cover page states, or None.

    None is a correct and common answer. Guessing a date would put a wrong
    edition boundary into the graph, which is worse than an undated edition —
    version identity falls back to a checksum, which is honest about what we
    could not read.
    """
    for pattern in DATE_PATTERNS:
        match = pattern.search(cover_text)
        if match:
            try:
                return datetime.strptime(
                    f"{match['day']} {match['month']} {match['year']}", "%d %B %Y"
                ).date()
            except ValueError:
                continue
    return None
```

Add `import re` and `from datetime import date, datetime` if absent. Add `effective_date`
to `ExtractedDocument` in `sources/document.py` as `date | None = None`, and populate it in
`extract_document` from the cover-page text that stage already isolates.

- [ ] **Step 4: Write the version during document ingest**

In `backend/src/policy_grapher/ingest.py`, inside `_write_document` (the single-document
transaction), after the provenance calls and before the `:External` refresh:

```python
    merge_version(
        tx,
        document_slug=slug,
        effective_date=extracted.effective_date,
        checksum=checksum,
        source_uri=f"file://{path}",
    )
    link_supersession(tx, slug)
```

Compute `checksum` before the transaction opens, alongside the existing slug resolution:

```python
checksum = hashlib.sha256(path.read_bytes()).hexdigest()
```

Add `import hashlib` and `from policy_grapher.versions import link_supersession, merge_version`.
Both calls sit **inside** the existing `session.execute_write` so a failure rolls the whole
ingest back, exactly as the node and edge writes already do.

- [ ] **Step 5: Add the route**

In `backend/src/policy_grapher/routers/documents.py`:

```python
LIST_VERSIONS = """
MATCH (d:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion)
OPTIONAL MATCH (v)-[:SUPERSEDES]->(older:DocumentVersion)
RETURN v.version_id   AS version_id,
       v.effective_date AS effective_date,
       v.checksum     AS checksum,
       v.source_uri   AS source_uri,
       older.version_id AS supersedes
ORDER BY coalesce(v.effective_date, ''), v.ingested_at
"""


@router.get("/{slug}/versions", response_model=list[DocumentVersionOut])
def list_versions(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[DocumentVersionOut]:
    records, _, _ = driver.execute_query(
        LIST_VERSIONS,
        {"slug": slug},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    return [DocumentVersionOut(**dict(record)) for record in records]
```

Import `DocumentVersionOut` and `RoutingControl`. Note the route carries
`require_principal` like every other — the phase 0 property test in
`tests/test_routers.py` will fail if you forget.

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/test_versions.py -v`
Expected: PASS

- [ ] **Step 7: Write ADR-011**

Create `docs/specs/adr/ADR-011-instruments-have-versions.md` from the template. It must
state: `:Document` becomes the instrument identity and does not migrate; editions are
`:DocumentVersion` nodes because `document_name_unique` makes two same-named documents
impossible; identity is content-derived (date, else checksum prefix) for ADR-003's reason;
`effective_date` is optional and absence is recorded rather than guessed; the manifest path
creates no versions because a citation list describes no edition; and `SUPERSEDES` is the
one derived edge ingest rebuilds rather than appends, with the reason — editions do not
arrive in order — and the boundary that this must not extend to edges carrying a human
judgement.

It must **also** record two behaviours added during Task 1's review, which the rest of this
plan predates:

- **A same-date, different-checksum ingest raises rather than absorbing.** Addressing by date
  alone keeps the id citable, but a corrected reissue bearing the same nominal date is a real
  shape, and `ON CREATE SET` would silently discard its content. `merge_version` compares the
  stored checksum and raises `VersionConflictError`. The operator decides, because the graph
  cannot tell a better scan of one edition from a distinct reissue, and guessing either way
  puts a wrong edition boundary in.
- **An unknown document slug raises `UnknownDocumentError`** rather than returning a
  plausible id for a version that was never written.

And one known limitation to state plainly rather than leave implicit in a `coalesce`:
**undated editions sort as oldest.** For an instrument mixing dated and undated editions there
is no honest ordering — ingest order is not publication order — and this at least gets the
common shape right: an undated scan of an old issuance, superseded by a dated current one.

- [ ] **Step 8: Run everything and commit**

Run: `cd backend && uv run pytest`
Expected: PASS

```bash
git add backend/src/policy_grapher backend/tests docs/specs/adr/ADR-011-instruments-have-versions.md
git commit -m "feat: ingesting a document records the edition it came from"
```

---

## Done when

- A PDF ingest produces exactly one `:DocumentVersion`; re-ingesting it produces none
- A second, newer edition produces a `SUPERSEDES` edge pointing at the first
- An edition arriving out of order lands in the right place in the chain
- The manifest path still creates no versions
- `GET /documents/{slug}/versions` requires a principal and reports the chain
- ADR-011 exists; `uv run pytest` passes

Phase 2 (text storage and chunking) can start.
