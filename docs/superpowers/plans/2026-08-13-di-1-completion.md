# DI-1 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the nine endpoints and one UI route SPEC-001 still names but DI-1 has not built, closing EPIC-001 at 18 of 18 stories.

**Architecture:** Routes split into FastAPI routers so `main.py` reduces to app assembly and lifespan. Document and reference Cypher lives in a new `documents.py`, mirroring what `graph.py` does for the graph view; `query.py` holds the raw-Cypher passthrough and its value coercion. Routers resolve the driver and settings through injectable dependencies backed by `request.app.state`.

**Tech Stack:** Python 3.14 · FastAPI · Pydantic v2 · neo4j driver v6 · uv · pytest · testcontainers — React 19 · Vite 6 · TypeScript · vitest 3

**Spec:** [`docs/superpowers/specs/2026-08-13-di-1-completion-design.md`](../specs/2026-08-13-di-1-completion-design.md)
Behavioural authority: [SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md). Decisions: [ADR-001](../../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md), [ADR-002](../../specs/adr/ADR-002-external-references-and-corpus-first-graph.md), [ADR-003](../../specs/adr/ADR-003-slug-identifiers.md), [ADR-004](../../specs/adr/ADR-004-unrestricted-cypher-in-di-1.md).

---

## Global Constraints

Copied from the design and verified against the running system on 2026-08-13. Every task's requirements implicitly include this section.

- **Python `>=3.14`**; **neo4j driver v6** — `driver.execute_query(cypher, params, database_=..., routing_=RoutingControl.READ|WRITE)`. Never `session.run` or `write_transaction`.
- **Labels and properties are exact:** `Document`, extra label `External`, properties `slug`, `name`, `reference_role`. Never `type`.
- **Relationship type is exact:** `REFERENCES`, directed source → target.
- **Baseline to preserve:** 71 backend tests, 21 frontend tests, all passing, output pristine. 31 backend tests run without Docker (`-m "not integration"`) and that must stay true.
- **Docker socket access needs `sg docker -c "..."`** on this machine — the shell session predates its `docker` group membership. This must never appear in committed files.
- **Frontend commands run in the container:** `sg docker -c "docker compose exec -T frontend npm ..."`. Do **not** use `docker compose run` or `docker compose build` — both relabel the SELinux mount and break the running frontend.
- **Never `mv` a file into `frontend/src`** — a new inode arrives with the host's SELinux label and the container cannot read it. Edit in place.
- **`references` and `referenced_by` carry slugs, not names.**
- **CORS allows all origins; no auth.** `POST /query` ships unrestricted per ADR-004.
- Corpus facts, unchanged: 23 corpus documents, 415 external, **438** total, **672** `REFERENCES` edges, 72 corpus→corpus.

---

## File Structure

```
backend/src/policy_grapher/
  main.py                 MODIFIED — app assembly, lifespan, router registration only
  dependencies.py         NEW — get_driver, get_app_settings
  routers/__init__.py     NEW
  routers/admin.py        NEW — GET /health · POST /ingest · POST /reset
  routers/documents.py    NEW — 5 document routes + 2 reference routes
  routers/graph.py        NEW — GET /graph · POST /query
  documents.py            NEW — document and reference Cypher
  query.py                NEW — run_cypher + coerce
  models.py               MODIFIED — + DocumentIn, DocumentOut, ResetResult, QueryRequest
  db.py                   MODIFIED — clear_graph returns counts
  graph.py, ingest.py, slugs.py, csv_source.py, config.py   unchanged

backend/tests/
  test_routers.py         NEW — the refactor's guard
  test_documents.py       NEW
  test_references.py      NEW
  test_query.py           NEW
  test_reset.py           NEW

frontend/src/
  api/types.ts            MODIFIED — + DocumentIn, DocumentOut, ResetResult
  api/client.ts           MODIFIED — 204 handling + nine methods
  api/client.test.ts      MODIFIED
  views/DocumentTable.tsx NEW
  views/DocumentTable.test.tsx NEW
  App.tsx                 MODIFIED — /documents route
```

---

## Task 1: Router refactor

Pure restructure. No behaviour changes, no new endpoints. The verification is that all 71 existing backend tests pass untouched.

**Files:**
- Create: `backend/src/policy_grapher/dependencies.py`, `routers/__init__.py`, `routers/admin.py`, `routers/graph.py`
- Create: `backend/tests/test_routers.py`
- Modify: `backend/src/policy_grapher/main.py`

**Interfaces:**
- Consumes: `Settings`, `create_driver`, `apply_constraints`, `is_graph_empty`, `ingest_file`, `build_graph`, `UnknownDocumentError`, `CsvSourceError`, existing models.
- Produces: `dependencies.get_driver(request) -> Driver`, `dependencies.get_app_settings(request) -> Settings`, `routers.admin.router`, `routers.graph.router`. `main.maybe_autoingest` and `main.lifespan` keep their current names and signatures — `conftest.py` monkeypatches `main.get_settings`, and `lifespan` must keep calling it by that name or every integration fixture breaks.

- [ ] **Step 1: Write the guard test**

`backend/tests/test_routers.py`:

```python
"""The refactor must not move any route or change any status code."""

import pytest

from policy_grapher.main import app

pytestmark = pytest.mark.integration

EXPECTED_ROUTES = {
    ("/health", "GET"),
    ("/ingest", "POST"),
    ("/graph", "GET"),
}


def registered_routes() -> set[tuple[str, str]]:
    found = set()
    for route in app.routes:
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}:
            found.add((route.path, method))
    return found


def test_every_expected_route_is_registered():
    assert EXPECTED_ROUTES <= registered_routes()


def test_no_route_is_registered_twice():
    paths = [
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}
    ]
    assert len(paths) == len(set(paths))


def test_health_still_serves_through_the_router(client_with_graph):
    response = client_with_graph.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_routers.py -v"
```

Expected: the first two tests PASS (routes exist in `main.py` today), the third PASSES too. This test is a *characterisation* test — it is green before and must stay green after. Record that it passed before the refactor; that is the evidence it is guarding something real rather than describing the new structure.

- [ ] **Step 3: Write `dependencies.py`**

```python
"""Request-scoped access to state the lifespan puts on the app."""

from fastapi import Request
from neo4j import Driver

from policy_grapher.config import Settings


def get_driver(request: Request) -> Driver:
    return request.app.state.driver


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings
```

- [ ] **Step 4: Write `routers/admin.py`** (reset comes in Task 4)

`backend/src/policy_grapher/routers/__init__.py` is empty.

```python
from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.csv_source import CsvSourceError
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.ingest import ingest_file
from policy_grapher.models import IngestRequest, IngestResult

router = APIRouter(tags=["admin"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/ingest", response_model=IngestResult)
def ingest(
    body: IngestRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> IngestResult:
    try:
        return ingest_file(
            driver, settings.neo4j_database, body.filename, settings.data_dir
        )
    except CsvSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 5: Write `routers/graph.py`** (query comes in Task 8)

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.models import GraphOut

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=GraphOut)
def graph(
    include_external: bool = False,
    expand: str | None = None,
    limit: int | None = Query(default=None, ge=0),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> GraphOut:
    effective_limit = settings.graph_render_cap if limit is None else limit
    try:
        return build_graph(
            driver,
            settings.neo4j_database,
            include_external=include_external,
            expand=expand,
            limit=effective_limit,
        )
    except UnknownDocumentError as exc:
        raise HTTPException(
            status_code=404, detail=f"No document with slug {exc.args[0]!r}."
        ) from exc
```

- [ ] **Step 6: Reduce `main.py`**

Keep `maybe_autoingest` and `lifespan` exactly as they are — same names, same bodies, same module. Replace everything below the CORS middleware with router registration, and drop the now-unused route imports.

```python
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from policy_grapher.config import Settings, get_settings
from policy_grapher.csv_source import CsvSourceError
from policy_grapher.db import apply_constraints, create_driver, is_graph_empty
from policy_grapher.ingest import ingest_file
from policy_grapher.models import IngestResult
from policy_grapher.routers import admin, graph

logger = logging.getLogger(__name__)


def maybe_autoingest(driver, settings: Settings) -> IngestResult | None:
    ...  # unchanged — do not edit this function


@asynccontextmanager
async def lifespan(app: FastAPI):
    ...  # unchanged — do not edit this function


app = FastAPI(title="Policy Grapher", version="0.1.0", lifespan=lifespan)

# DI-1 is local-only and unauthenticated. See SPEC-001 (CORS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(graph.router)
```

- [ ] **Step 7: Run the whole backend suite**

```bash
cd backend && sg docker -c "uv run pytest -q"
```

Expected: **74 passed** (71 existing + 3 new), zero warnings. If any pre-existing test fails, the refactor changed behaviour — fix the refactor, never the test.

- [ ] **Step 8: Confirm the container-free suite still runs**

```bash
cd backend && uv run pytest -m "not integration" -q
```

Expected: 31 passed, no container started.

- [ ] **Step 9: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_routers.py
git commit -m "refactor: split routes into routers, resolve state through dependencies"
```

---

## Task 2: ADR-005 — amending ADR-003

Documentation only. Gates Task 6.

**Files:**
- Create: `docs/specs/adr/ADR-005-slug-assignment-over-the-name-set.md`
- Modify: `docs/specs/adr/ADR-003-slug-identifiers.md` (one line only)

**Interfaces:** none.

- [ ] **Step 1: Write the ADR**

Follow `docs/specs/adr/TEMPLATE-adr.md`. Status Accepted, date 2026-08-13, Deciders "Project owner". It **amends** ADR-003; it does not supersede it. Record these three decisions and nothing else:

1. **Ingest assigns slugs over the whole name set, not per name.** When a base slug is contested every contender takes a `-<sha8>` suffix. ADR-003's literal rule — suffix the second arrival — is ingest-order dependent and therefore contradicts ADR-003's own promise that slugs are stable across ingest order. The sample corpus contests twice (`Military Standard 882E` / `Military-Standard 882E`, and two Assistant Secretary of Defense names that collide only after the 80-character truncation), so this path runs on every ingest.
2. **At incremental creation the incumbent keeps its bare slug; the newcomer takes the suffix.** Consequence, stated plainly: ingest-time and create-time assignment can diverge, so a reset-and-reingest may produce different slugs than incremental creation did. URL stability for existing documents was judged worth that.
3. **A suffixed slug can reach 89 characters** against ADR-003's stated 80, because the suffix is appended after truncation. Nothing enforces 80 anywhere; this records the real bound.

Under Consequences, note that a name duplicating an existing document verbatim is a `409` and is a different case from a contested slug, which succeeds.

- [ ] **Step 2: Cross-reference from ADR-003**

Add one line directly beneath ADR-003's status line, changing nothing else in that file — it is a frozen dated record:

```markdown
> **Amended by [ADR-005](ADR-005-slug-assignment-over-the-name-set.md)** (2026-08-13): slug
> assignment is a function of the whole name set, and incremental creation resolves
> contested slugs in favour of the incumbent.
```

- [ ] **Step 3: Verify links resolve**

```bash
python3 /home/rhagan/.claude/skills/synced/project-docs-init/scripts/scaffold.py check --root .
```

Expected: no new broken links. One pre-existing false positive in `superpowers/plans/2026-08-12-di-1-spine.md` is expected — it is a link inside a fenced code block.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/adr
git commit -m "docs: ADR-005 amends ADR-003 on slug assignment over the name set"
```

---

## Task 3: STORY-032 — a TypeScript error fails the test command

**Files:**
- Modify: `frontend/package.json`

**Interfaces:** none.

- [ ] **Step 1: Change the test script**

```json
    "test": "tsc -b && vitest run",
```

Leave `build` as `tsc -b && vite build`.

- [ ] **Step 2: Prove it discriminates**

Introduce a deliberate type error — in `frontend/src/api/client.ts`, temporarily change `const BASE = '/api'` to `const BASE: number = '/api'`.

```bash
sg docker -c "docker compose exec -T frontend npm test"
```

Expected: RED, failing on `TS2322` before vitest runs at all. Restore the line, re-run, expect 21 passed. Put **both** outputs in the report — that is the evidence the gate works.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json
git commit -m "build: type-check the frontend before running its tests"
```

---

## Task 4: STORY-028 — `POST /reset`

**Files:**
- Modify: `backend/src/policy_grapher/db.py`, `models.py`, `routers/admin.py`
- Create: `backend/tests/test_reset.py`

**Interfaces:**
- Consumes: `get_driver`, `get_app_settings`.
- Produces: `db.clear_graph(driver, database) -> tuple[int, int]` (nodes, relationships deleted) — a **changed return type**; existing callers in `conftest.py` and `test_ingest.py` ignore it and need no edit. `models.ResetResult`. Route `POST /reset`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_reset.py`:

```python
from pathlib import Path

import pytest
from neo4j import RoutingControl

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


def node_count(driver, database) -> int:
    records, _, _ = driver.execute_query(
        "MATCH (n) RETURN count(n) AS n",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["n"]


def test_reset_empties_a_loaded_graph_and_reports_counts(client_with_graph, driver, database):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    assert node_count(driver, database) == 438

    response = client_with_graph.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"nodes_deleted": 438, "relationships_deleted": 672}
    assert node_count(driver, database) == 0


def test_reset_on_an_empty_graph_reports_zeroes(client_with_graph, driver, database):
    response = client_with_graph.post("/reset")

    assert response.status_code == 200
    assert response.json() == {"nodes_deleted": 0, "relationships_deleted": 0}


def test_reset_does_not_retrigger_auto_ingest(client_with_graph, driver, database):
    """Auto-ingest is a startup check. Emptying the graph must not reload it."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    client_with_graph.post("/reset")

    client_with_graph.get("/health")

    assert node_count(driver, database) == 0
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_reset.py -v"
```

Expected: 404 on `POST /reset` — the route does not exist.

- [ ] **Step 3: Make `clear_graph` return counts**

Replace `clear_graph` in `db.py`:

```python
def clear_graph(driver: Driver, database: str) -> tuple[int, int]:
    """Delete everything. Returns (nodes_deleted, relationships_deleted)."""
    _, summary, _ = driver.execute_query(
        "MATCH (n) DETACH DELETE n",
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    return summary.counters.nodes_deleted, summary.counters.relationships_deleted
```

- [ ] **Step 4: Add the model**

In `models.py`:

```python
class ResetResult(BaseModel):
    nodes_deleted: int
    relationships_deleted: int
```

- [ ] **Step 5: Add the route to `routers/admin.py`**

Import `clear_graph` from `policy_grapher.db` and `ResetResult` from `policy_grapher.models`, then:

```python
@router.post("/reset", response_model=ResetResult)
def reset(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> ResetResult:
    nodes, relationships = clear_graph(driver, settings.neo4j_database)
    return ResetResult(nodes_deleted=nodes, relationships_deleted=relationships)
```

- [ ] **Step 6: Run the tests, then the full suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_reset.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: 3 passed, then 77 passed overall.

- [ ] **Step 7: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_reset.py
git commit -m "feat: POST /reset empties the graph and reports what it deleted"
```

---

## Task 5: STORY-005 — read endpoints

**Files:**
- Create: `backend/src/policy_grapher/documents.py`, `routers/documents.py`, `backend/tests/test_documents.py`
- Modify: `backend/src/policy_grapher/models.py`, `main.py`

**Interfaces:**
- Consumes: `get_driver`, `get_app_settings`.
- Produces: `models.DocumentOut`; `documents.DocumentNotFoundError`; `documents.list_documents(driver, database) -> list[DocumentOut]`; `documents.get_document(driver, database, slug) -> DocumentOut`; routes `GET /documents`, `GET /documents/{slug}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_documents.py`:

```python
import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


@pytest.fixture
def loaded(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    return client_with_graph


def test_list_returns_every_document_ordered_by_slug(loaded):
    body = loaded.get("/documents").json()

    assert len(body) == 438
    slugs = [doc["slug"] for doc in body]
    assert slugs == sorted(slugs)


def test_list_distinguishes_corpus_from_external(loaded):
    body = loaded.get("/documents").json()

    corpus = [doc for doc in body if not doc["is_external"]]
    external = [doc for doc in body if doc["is_external"]]

    assert len(corpus) == 23
    assert len(external) == 415
    assert all(doc["reference_role"] is not None for doc in corpus)
    assert all(doc["reference_role"] is None for doc in external)


def test_get_one_returns_both_directions_as_slugs(loaded):
    body = loaded.get("/documents/dodi-3115-14").json()

    assert body["slug"] == "dodi-3115-14"
    assert body["name"] == "DoDI 3115.14"
    assert body["reference_role"] == "Sub-Reference"
    assert body["is_external"] is False
    assert "public-law-116-92" in body["references"]
    assert body["references"] == sorted(body["references"])
    assert body["referenced_by"] == sorted(body["referenced_by"])


def test_an_external_document_is_referenced_but_references_nothing(loaded):
    body = loaded.get("/documents/public-law-116-92").json()

    assert body["is_external"] is True
    assert body["reference_role"] is None
    assert body["references"] == []
    assert "dodi-3115-14" in body["referenced_by"]


def test_reference_totals_match_the_corpus(loaded):
    body = loaded.get("/documents").json()

    assert sum(len(doc["references"]) for doc in body) == 672
    assert sum(len(doc["referenced_by"]) for doc in body) == 672


def test_unknown_slug_is_404(loaded):
    assert loaded.get("/documents/no-such-document").status_code == 404
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
```

Expected: 404s on every request — the routes do not exist.

- [ ] **Step 3: Add `DocumentOut`**

In `models.py`:

```python
class DocumentOut(BaseModel):
    slug: str
    name: str
    reference_role: str | None
    is_external: bool
    references: list[str] = Field(default_factory=list)
    referenced_by: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Write `documents.py`**

```python
"""Document and reference Cypher.

Knows nothing about HTTP, exactly as graph.py does not. Reference lists carry
slugs, not names — see the DI-1 completion design.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import DocumentOut

DOCUMENT_FIELDS = """
OPTIONAL MATCH (d)-[:REFERENCES]->(out:Document)
WITH d, collect(DISTINCT out.slug) AS references
OPTIONAL MATCH (d)<-[:REFERENCES]-(inc:Document)
WITH d, references, collect(DISTINCT inc.slug) AS referenced_by
RETURN d.slug AS slug, d.name AS name, d.reference_role AS reference_role,
       d:External AS is_external, references, referenced_by
"""

LIST_DOCUMENTS = f"MATCH (d:Document) {DOCUMENT_FIELDS} ORDER BY slug ASC"
GET_DOCUMENT = f"MATCH (d:Document {{slug: $slug}}) {DOCUMENT_FIELDS}"


class DocumentNotFoundError(LookupError):
    """No document with the requested slug exists."""


def _to_document(record) -> DocumentOut:
    # Neo4j has no list sort without APOC, so order the reference lists here.
    return DocumentOut(
        slug=record["slug"],
        name=record["name"],
        reference_role=record["reference_role"],
        is_external=record["is_external"],
        references=sorted(record["references"]),
        referenced_by=sorted(record["referenced_by"]),
    )


def _read(driver: Driver, database: str, cypher: str, params: dict | None = None):
    records, _, _ = driver.execute_query(
        cypher, params or {}, database_=database, routing_=RoutingControl.READ
    )
    return records


def list_documents(driver: Driver, database: str) -> list[DocumentOut]:
    return [_to_document(r) for r in _read(driver, database, LIST_DOCUMENTS)]


def get_document(driver: Driver, database: str, slug: str) -> DocumentOut:
    records = _read(driver, database, GET_DOCUMENT, {"slug": slug})
    if not records:
        raise DocumentNotFoundError(slug)
    return _to_document(records[0])
```

- [ ] **Step 5: Write `routers/documents.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.documents import (
    DocumentNotFoundError,
    get_document,
    list_documents,
)
from policy_grapher.models import DocumentOut

router = APIRouter(prefix="/documents", tags=["documents"])


def _not_found(slug: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No document with slug {slug!r}.")


@router.get("", response_model=list[DocumentOut])
def list_all(
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> list[DocumentOut]:
    return list_documents(driver, settings.neo4j_database)


@router.get("/{slug}", response_model=DocumentOut)
def read_one(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> DocumentOut:
    try:
        return get_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
```

Register it in `main.py`: add `documents` to the `from policy_grapher.routers import ...` line and `app.include_router(documents.router)`.

Note the empty path on `list_all`: with `prefix="/documents"`, `@router.get("")` serves `/documents` exactly. `@router.get("/")` would serve `/documents/` and redirect.

- [ ] **Step 6: Run the tests, then the full suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: 6 passed, then 83 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_documents.py
git commit -m "feat: list documents and read one with both reference directions"
```

---

## Task 6: STORY-006 — create, update, delete

Needs ADR-005 (Task 2).

**Files:**
- Modify: `backend/src/policy_grapher/documents.py`, `models.py`, `routers/documents.py`
- Modify: `backend/tests/test_documents.py`

**Interfaces:**
- Consumes: `slugs.base_slug`, `slugs.hash_suffix`; everything from Task 5.
- Produces: `models.DocumentIn`; `documents.NameConflictError`, `NameMismatchError`, `ExternalDocumentError`; `documents.create_document(driver, database, name, reference_role) -> DocumentOut`; `documents.update_document(driver, database, slug, name, reference_role) -> DocumentOut`; `documents.delete_document(driver, database, slug) -> None`; routes `POST /documents`, `PUT /documents/{slug}`, `DELETE /documents/{slug}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_documents.py`:

```python
def test_create_returns_201_with_a_generated_slug(client_with_graph):
    response = client_with_graph.post(
        "/documents", json={"name": "DoDD 9999.01", "reference_role": "Root Reference"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "dodd-9999-01"
    assert body["is_external"] is False
    assert body["references"] == []
    assert body["referenced_by"] == []


def test_create_rejects_a_duplicate_name_with_409(client_with_graph):
    payload = {"name": "DoDD 9999.01", "reference_role": "Root Reference"}
    client_with_graph.post("/documents", json=payload)

    response = client_with_graph.post("/documents", json=payload)

    assert response.status_code == 409


def test_a_contested_slug_suffixes_the_newcomer_and_leaves_the_incumbent(client_with_graph):
    """ADR-005: the incumbent keeps its bare slug."""
    first = client_with_graph.post(
        "/documents", json={"name": "Military Standard 882E", "reference_role": "Sub-Reference"}
    ).json()
    second = client_with_graph.post(
        "/documents", json={"name": "Military-Standard 882E", "reference_role": "Sub-Reference"}
    ).json()

    assert first["slug"] == "military-standard-882e"
    assert second["slug"].startswith("military-standard-882e-")
    assert second["slug"] != first["slug"]
    # The incumbent is untouched.
    assert client_with_graph.get("/documents/military-standard-882e").json()["name"] == (
        "Military Standard 882E"
    )


def test_create_rejects_an_empty_name(client_with_graph):
    response = client_with_graph.post(
        "/documents", json={"name": "", "reference_role": "Root Reference"}
    )
    assert response.status_code == 422


def test_update_changes_only_the_reference_role(loaded):
    response = loaded.put(
        "/documents/dodi-3115-14",
        json={"name": "DoDI 3115.14", "reference_role": "Root Reference"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reference_role"] == "Root Reference"
    assert body["name"] == "DoDI 3115.14"
    # Relationships survive the edit.
    assert "public-law-116-92" in body["references"]


def test_update_with_a_mismatched_name_is_400(loaded):
    """SPEC-001's Definition of Done names this case explicitly."""
    response = loaded.put(
        "/documents/dodi-3115-14",
        json={"name": "Something Else", "reference_role": "Root Reference"},
    )

    assert response.status_code == 400
    assert loaded.get("/documents/dodi-3115-14").json()["reference_role"] == "Sub-Reference"


def test_update_on_an_external_document_is_400(loaded):
    """External documents have no reference_role by definition (ADR-002)."""
    response = loaded.put(
        "/documents/public-law-116-92",
        json={"name": "Public Law 116-92", "reference_role": "Root Reference"},
    )

    assert response.status_code == 400
    assert loaded.get("/documents/public-law-116-92").json()["reference_role"] is None


def test_update_an_unknown_slug_is_404(loaded):
    response = loaded.put(
        "/documents/no-such-document",
        json={"name": "Whatever", "reference_role": "Root Reference"},
    )
    assert response.status_code == 404


def test_delete_removes_the_document_and_its_edges(loaded):
    before = loaded.get("/documents/dodd-5000-01").json()
    assert before["references"]

    assert loaded.delete("/documents/dodd-5000-01").status_code == 204

    assert loaded.get("/documents/dodd-5000-01").status_code == 404
    # Its former targets survive, minus the edge.
    survivor = loaded.get(f"/documents/{before['references'][0]}").json()
    assert "dodd-5000-01" not in survivor["referenced_by"]


def test_delete_an_unknown_slug_is_404(loaded):
    assert loaded.delete("/documents/no-such-document").status_code == 404
```

- [ ] **Step 2: Run and confirm they fail**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
```

Expected: the six Task 5 tests pass; the new ones fail with 405 Method Not Allowed (the path exists, the verb does not).

- [ ] **Step 3: Add `DocumentIn`**

In `models.py` — `Field` is already imported:

```python
class DocumentIn(BaseModel):
    name: str = Field(min_length=1)
    reference_role: str = Field(min_length=1)
```

- [ ] **Step 4: Extend `documents.py`**

Add the imports `from policy_grapher.slugs import base_slug, hash_suffix` and:

```python
SLUG_TAKEN = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"
NAME_TAKEN = "MATCH (d:Document {name: $name}) RETURN count(d) AS total"

CREATE_DOCUMENT = """
CREATE (d:Document {slug: $slug, name: $name, reference_role: $reference_role})
"""

UPDATE_ROLE = """
MATCH (d:Document {slug: $slug})
SET d.reference_role = $reference_role
"""

DELETE_DOCUMENT = "MATCH (d:Document {slug: $slug}) DETACH DELETE d"


class NameConflictError(ValueError):
    """A document with this name already exists."""


class NameMismatchError(ValueError):
    """The body's name does not match the addressed document."""


class ExternalDocumentError(ValueError):
    """The addressed document is external and has no reference_role."""


def _write(driver: Driver, database: str, cypher: str, params: dict):
    _, summary, _ = driver.execute_query(
        cypher, params, database_=database, routing_=RoutingControl.WRITE
    )
    return summary


def _count(driver: Driver, database: str, cypher: str, params: dict) -> int:
    return _read(driver, database, cypher, params)[0]["total"]


def allocate_slug(driver: Driver, database: str, name: str) -> str:
    """ADR-005: the incumbent keeps its bare slug, the newcomer takes the suffix."""
    base = base_slug(name)
    if _count(driver, database, SLUG_TAKEN, {"slug": base}) == 0:
        return base
    return f"{base}-{hash_suffix(name)}"


def create_document(
    driver: Driver, database: str, name: str, reference_role: str
) -> DocumentOut:
    if _count(driver, database, NAME_TAKEN, {"name": name}) > 0:
        raise NameConflictError(name)

    slug = allocate_slug(driver, database, name)
    _write(
        driver,
        database,
        CREATE_DOCUMENT,
        {"slug": slug, "name": name, "reference_role": reference_role},
    )
    return get_document(driver, database, slug)


def update_document(
    driver: Driver, database: str, slug: str, name: str, reference_role: str
) -> DocumentOut:
    current = get_document(driver, database, slug)  # raises DocumentNotFoundError
    if current.is_external:
        raise ExternalDocumentError(slug)
    if current.name != name:
        raise NameMismatchError(name)

    _write(driver, database, UPDATE_ROLE, {"slug": slug, "reference_role": reference_role})
    return get_document(driver, database, slug)


def delete_document(driver: Driver, database: str, slug: str) -> None:
    summary = _write(driver, database, DELETE_DOCUMENT, {"slug": slug})
    if summary.counters.nodes_deleted == 0:
        raise DocumentNotFoundError(slug)
```

- [ ] **Step 5: Add the routes**

In `routers/documents.py`, import the new names plus `Response`, and add:

```python
@router.post("", response_model=DocumentOut, status_code=201)
def create(
    body: DocumentIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> DocumentOut:
    try:
        return create_document(
            driver, settings.neo4j_database, body.name, body.reference_role
        )
    except NameConflictError as exc:
        raise HTTPException(
            status_code=409, detail=f"A document named {body.name!r} already exists."
        ) from exc


@router.put("/{slug}", response_model=DocumentOut)
def update(
    slug: str,
    body: DocumentIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> DocumentOut:
    try:
        return update_document(
            driver, settings.neo4j_database, slug, body.name, body.reference_role
        )
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    except ExternalDocumentError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{slug!r} is an external document and has no reference_role.",
        ) from exc
    except NameMismatchError as exc:
        raise HTTPException(
            status_code=400,
            detail="Body name does not match the addressed document; renaming means delete and recreate.",
        ) from exc


@router.delete("/{slug}", status_code=204)
def delete(
    slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    try:
        delete_document(driver, settings.neo4j_database, slug)
    except DocumentNotFoundError as exc:
        raise _not_found(slug) from exc
    return Response(status_code=204)
```

Order matters: `ExternalDocumentError` and `NameMismatchError` both subclass `ValueError`, so catch each by its own name rather than catching `ValueError`.

- [ ] **Step 6: Run the tests, then the full suite**

```bash
cd backend && sg docker -c "uv run pytest tests/test_documents.py -v"
cd backend && sg docker -c "uv run pytest -q"
```

Expected: 16 passed, then 93 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_documents.py
git commit -m "feat: create, update and delete documents addressed by slug"
```

---

## Task 7: STORY-027 — reference edges

**Files:**
- Modify: `backend/src/policy_grapher/documents.py`, `routers/documents.py`
- Create: `backend/tests/test_references.py`

**Interfaces:**
- Produces: `documents.SelfReferenceError`; `documents.add_reference(driver, database, source, target) -> None`; `documents.remove_reference(driver, database, source, target) -> None`; routes `POST` and `DELETE /documents/{slug}/references/{target_slug}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_references.py`:

```python
import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


@pytest.fixture
def loaded(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    return client_with_graph


def test_adding_an_edge_shows_up_in_both_directions(loaded):
    response = loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")

    assert response.status_code == 204
    assert "dodi-3115-14" in loaded.get("/documents/dodd-5000-01").json()["references"]
    assert "dodd-5000-01" in loaded.get("/documents/dodi-3115-14").json()["referenced_by"]


def test_adding_the_same_edge_twice_is_idempotent(loaded):
    loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")
    loaded.post("/documents/dodd-5000-01/references/dodi-3115-14")

    references = loaded.get("/documents/dodd-5000-01").json()["references"]
    assert references.count("dodi-3115-14") == 1


def test_a_self_reference_is_400(loaded):
    response = loaded.post("/documents/dodd-5000-01/references/dodd-5000-01")

    assert response.status_code == 400
    assert "dodd-5000-01" not in loaded.get("/documents/dodd-5000-01").json()["references"]


def test_an_unknown_endpoint_is_404(loaded):
    assert loaded.post("/documents/no-such-doc/references/dodi-3115-14").status_code == 404
    assert loaded.post("/documents/dodd-5000-01/references/no-such-doc").status_code == 404


def test_removing_an_edge_leaves_both_documents(loaded):
    before = loaded.get("/documents/dodd-5000-01").json()["references"]
    target = before[0]

    assert loaded.delete(f"/documents/dodd-5000-01/references/{target}").status_code == 204

    assert target not in loaded.get("/documents/dodd-5000-01").json()["references"]
    assert loaded.get(f"/documents/{target}").status_code == 200
    assert loaded.get("/documents/dodd-5000-01").status_code == 200


def test_removing_an_absent_edge_is_still_204(loaded):
    """The contract is 'this edge does not exist afterwards'."""
    response = loaded.delete("/documents/dodi-3115-14/references/dodd-5000-01")
    assert response.status_code == 204
```

- [ ] **Step 2: Run and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_references.py -v"
```

Expected: 404 — the routes do not exist.

- [ ] **Step 3: Extend `documents.py`**

```python
ADD_REFERENCE = """
MATCH (source:Document {slug: $source})
MATCH (target:Document {slug: $target})
MERGE (source)-[:REFERENCES]->(target)
"""

REMOVE_REFERENCE = """
MATCH (source:Document {slug: $source})-[r:REFERENCES]->(target:Document {slug: $target})
DELETE r
"""


class SelfReferenceError(ValueError):
    """A document may not reference itself."""


def _require_document(driver: Driver, database: str, slug: str) -> None:
    if _count(driver, database, SLUG_TAKEN, {"slug": slug}) == 0:
        raise DocumentNotFoundError(slug)


def add_reference(driver: Driver, database: str, source: str, target: str) -> None:
    if source == target:
        raise SelfReferenceError(source)
    _require_document(driver, database, source)
    _require_document(driver, database, target)
    _write(driver, database, ADD_REFERENCE, {"source": source, "target": target})


def remove_reference(driver: Driver, database: str, source: str, target: str) -> None:
    _require_document(driver, database, source)
    _require_document(driver, database, target)
    # No-op when the edge is absent: the contract is the end state, not the delta.
    _write(driver, database, REMOVE_REFERENCE, {"source": source, "target": target})
```

`add_reference` checks for self-reference *before* existence, so `POST /documents/x/references/x` on an unknown slug returns 400 rather than 404 — the request is malformed regardless of whether the document exists.

- [ ] **Step 4: Add the routes**

```python
@router.post("/{slug}/references/{target_slug}", status_code=204)
def add_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    try:
        add_reference(driver, settings.neo4j_database, slug, target_slug)
    except SelfReferenceError as exc:
        raise HTTPException(
            status_code=400, detail="A document may not reference itself."
        ) from exc
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)


@router.delete("/{slug}/references/{target_slug}", status_code=204)
def remove_ref(
    slug: str,
    target_slug: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    try:
        remove_reference(driver, settings.neo4j_database, slug, target_slug)
    except DocumentNotFoundError as exc:
        raise _not_found(exc.args[0]) from exc
    return Response(status_code=204)
```

- [ ] **Step 5: Run the tests, then the full suite**

Expected: 6 passed, then 99 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_references.py
git commit -m "feat: add and remove references between documents"
```

---

## Task 8: STORY-008 — `POST /query`

Ships unrestricted per [ADR-004](../../specs/adr/ADR-004-unrestricted-cypher-in-di-1.md): no read-only enforcement, no timeout, no row cap. That is a deliberate, recorded risk acceptance, not an oversight — do not add limits.

**Files:**
- Create: `backend/src/policy_grapher/query.py`, `backend/tests/test_query.py`
- Modify: `backend/src/policy_grapher/models.py`, `routers/graph.py`

**Interfaces:**
- Produces: `models.QueryRequest`; `query.coerce(value) -> object`; `query.run_cypher(driver, database, cypher) -> list[dict]`; route `POST /query`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_query.py`:

```python
import pytest

from policy_grapher.query import coerce

SAMPLE = "dod_policy_references_08122026.csv"


class FakeNode:
    """Stands in for neo4j.graph.Node without a database."""

    def __init__(self, labels, properties):
        self.labels = labels
        self._properties = properties

    def __iter__(self):
        return iter(self._properties)

    def __getitem__(self, key):
        return self._properties[key]

    def keys(self):
        return self._properties.keys()


# --- coercion, no database ---------------------------------------------

def test_scalars_pass_through_unchanged():
    assert coerce("a") == "a"
    assert coerce(3) == 3
    assert coerce(1.5) == 1.5
    assert coerce(True) is True
    assert coerce(None) is None


def test_nested_collections_are_coerced_element_wise():
    assert coerce([1, ["a", None]]) == [1, ["a", None]]
    assert coerce({"k": [1, 2]}) == {"k": [1, 2]}


def test_a_value_with_no_json_representation_falls_back_to_str():
    class Opaque:
        def __str__(self):
            return "opaque-value"

    assert coerce(Opaque()) == "opaque-value"


# --- against the real driver -------------------------------------------

@pytest.mark.integration
def test_returning_a_whole_node_does_not_500(client_with_graph):
    """`MATCH (n) RETURN n` is the first thing a Cypher-fluent user types."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH (d:Document {slug: 'dodi-3115-14'}) RETURN d"}
    )

    assert response.status_code == 200
    record = response.json()[0]["d"]
    assert "Document" in record["labels"]
    assert record["properties"]["name"] == "DoDI 3115.14"


@pytest.mark.integration
def test_returning_a_relationship_is_serialised(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH ()-[r:REFERENCES]->() RETURN r LIMIT 1"}
    )

    assert response.json()[0]["r"]["type"] == "REFERENCES"


@pytest.mark.integration
def test_a_temporal_value_survives_serialisation(client_with_graph):
    """No stored value is temporal, but RETURN datetime() is valid Cypher."""
    response = client_with_graph.post("/query", json={"cypher": "RETURN datetime() AS now"})

    assert response.status_code == 200
    assert isinstance(response.json()[0]["now"], str)


@pytest.mark.integration
def test_scalar_aggregates_come_back_plain(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    response = client_with_graph.post(
        "/query", json={"cypher": "MATCH (d:Document) RETURN count(d) AS total"}
    )

    assert response.json() == [{"total": 438}]


@pytest.mark.integration
def test_writes_are_permitted(client_with_graph):
    """ADR-004: no read-only enforcement in DI-1."""
    client_with_graph.post(
        "/query", json={"cypher": "CREATE (:Document {slug: 'from-query', name: 'From Query'})"}
    )

    assert client_with_graph.get("/documents/from-query").status_code == 200


@pytest.mark.integration
def test_invalid_cypher_is_400_not_500(client_with_graph):
    response = client_with_graph.post("/query", json={"cypher": "NOT VALID CYPHER"})

    assert response.status_code == 400
```

- [ ] **Step 2: Run and confirm it fails**

```bash
cd backend && sg docker -c "uv run pytest tests/test_query.py -v"
```

Expected: `ModuleNotFoundError: No module named 'policy_grapher.query'`.

- [ ] **Step 3: Write `query.py`**

```python
"""Raw Cypher passthrough.

Unrestricted by decision — no read-only enforcement, no timeout, no row cap.
See ADR-004; that acceptance is bounded by DI-1 staying local-only.
"""

from neo4j import Driver, RoutingControl
from neo4j.graph import Node, Path, Relationship

JSON_SCALARS = (str, int, float, bool)


def coerce(value: object) -> object:
    """Turn driver values into something FastAPI can serialise.

    `MATCH (n) RETURN n` yields Node objects, and `RETURN datetime()` yields a
    temporal — neither is JSON-serialisable, and both are things a user types.
    """
    if isinstance(value, Node):
        return {"labels": sorted(value.labels), "properties": dict(value)}
    if isinstance(value, Relationship):
        return {"type": value.type, "properties": dict(value)}
    if isinstance(value, Path):
        return {
            "nodes": [coerce(node) for node in value.nodes],
            "relationships": [coerce(rel) for rel in value.relationships],
        }
    if isinstance(value, list):
        return [coerce(item) for item in value]
    if isinstance(value, dict):
        return {key: coerce(item) for key, item in value.items()}
    if value is None or isinstance(value, JSON_SCALARS):
        return value
    return str(value)


def run_cypher(driver: Driver, database: str, cypher: str) -> list[dict]:
    # WRITE routing: ADR-004 permits mutation through this endpoint.
    records, _, _ = driver.execute_query(
        cypher, database_=database, routing_=RoutingControl.WRITE
    )
    return [{key: coerce(value) for key, value in record.items()} for record in records]
```

Order matters: `Node` and `Relationship` are checked before `dict`, and `bool` before the numeric passthrough is irrelevant because both pass through unchanged.

- [ ] **Step 4: Add the model and the route**

In `models.py`:

```python
class QueryRequest(BaseModel):
    cypher: str = Field(min_length=1)
```

In `routers/graph.py`, import `Neo4jError` from `neo4j.exceptions`, plus `QueryRequest` and `run_cypher`:

```python
@router.post("/query")
def query(
    body: QueryRequest,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
) -> list[dict]:
    try:
        return run_cypher(driver, settings.neo4j_database, body.cypher)
    except Neo4jError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 5: Run the tests, then the full suite**

Expected: 10 passed (3 without Docker), then 109 passed. Confirm `-m "not integration"` is now 34.

- [ ] **Step 6: Commit**

```bash
git add backend/src/policy_grapher backend/tests/test_query.py
git commit -m "feat: POST /query executes raw Cypher and serialises graph values"
```

---

## Task 9: Typed client methods for all nine endpoints

**Files:**
- Modify: `frontend/src/api/types.ts`, `api/client.ts`, `api/client.test.ts`

**Interfaces:**
- Produces: `types.DocumentIn`, `types.DocumentOut`, `types.ResetResult`; client functions `listDocuments`, `getDocument`, `createDocument`, `updateDocument`, `deleteDocument`, `addReference`, `removeReference`, `reset`, `runQuery`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/api/client.test.ts`, following the existing `mockJson` pattern. Add a helper for empty responses first:

```ts
function mockNoContent() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 204,
    json: async () => {
      throw new Error('204 responses have no body')
    },
    text: async () => '',
  })
}

describe('documents', () => {
  it('lists documents', async () => {
    const fetchMock = mockJson([])
    vi.stubGlobal('fetch', fetchMock)

    await listDocuments()

    expect(fetchMock).toHaveBeenCalledWith('/api/documents', expect.anything())
  })

  it('reads one by slug', async () => {
    const fetchMock = mockJson({ slug: 'dodd-5000-01' })
    vi.stubGlobal('fetch', fetchMock)

    await getDocument('dodd-5000-01')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/dodd-5000-01')
  })

  it('posts a new document', async () => {
    const fetchMock = mockJson({ slug: 'dodd-9999-01' }, 201)
    vi.stubGlobal('fetch', fetchMock)

    await createDocument({ name: 'DoDD 9999.01', reference_role: 'Root Reference' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      name: 'DoDD 9999.01',
      reference_role: 'Root Reference',
    })
  })

  it('resolves rather than throwing on a 204', async () => {
    // request() calls response.json() unconditionally today, which throws on an
    // empty body — five of the nine new endpoints return 204.
    vi.stubGlobal('fetch', mockNoContent())

    await expect(deleteDocument('dodd-5000-01')).resolves.toBeUndefined()
  })

  it('adds a reference at the nested path', async () => {
    const fetchMock = mockNoContent()
    vi.stubGlobal('fetch', fetchMock)

    await addReference('dodd-5000-01', 'dodi-3115-14')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/dodd-5000-01/references/dodi-3115-14')
    expect(init.method).toBe('POST')
  })
})

describe('runQuery', () => {
  it('posts the cypher string', async () => {
    const fetchMock = mockJson([{ total: 438 }])
    vi.stubGlobal('fetch', fetchMock)

    const rows = await runQuery('MATCH (d:Document) RETURN count(d) AS total')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      cypher: 'MATCH (d:Document) RETURN count(d) AS total',
    })
    expect(rows).toEqual([{ total: 438 }])
  })
})
```

Extend the existing `mockJson` to take a status argument: `function mockJson(body: unknown, status = 200)` — it already does.

- [ ] **Step 2: Run and confirm they fail**

```bash
sg docker -c "docker compose exec -T frontend npm test"
```

Expected: type errors from `tsc -b` (Task 3's gate) on the unexported names, before vitest runs.

- [ ] **Step 3: Add the types**

In `types.ts`:

```ts
export interface DocumentIn {
  name: string
  reference_role: string
}

export interface DocumentOut {
  slug: string
  name: string
  reference_role: string | null
  is_external: boolean
  references: string[]
  referenced_by: string[]
}

export interface ResetResult {
  nodes_deleted: number
  relationships_deleted: number
}
```

- [ ] **Step 4: Handle 204 in `request`**

In `client.ts`, insert immediately before the final `return`:

```ts
  // 204 has no body; json() would throw.
  if (response.status === 204) return undefined as T
```

- [ ] **Step 5: Add the nine methods**

```ts
export function listDocuments(): Promise<DocumentOut[]> {
  return request<DocumentOut[]>('/documents')
}

export function getDocument(slug: string): Promise<DocumentOut> {
  return request<DocumentOut>(`/documents/${encodeURIComponent(slug)}`)
}

export function createDocument(document: DocumentIn): Promise<DocumentOut> {
  return request<DocumentOut>('/documents', {
    method: 'POST',
    body: JSON.stringify(document),
  })
}

export function updateDocument(slug: string, document: DocumentIn): Promise<DocumentOut> {
  return request<DocumentOut>(`/documents/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(document),
  })
}

export function deleteDocument(slug: string): Promise<void> {
  return request<void>(`/documents/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

export function addReference(slug: string, targetSlug: string): Promise<void> {
  return request<void>(
    `/documents/${encodeURIComponent(slug)}/references/${encodeURIComponent(targetSlug)}`,
    { method: 'POST' },
  )
}

export function removeReference(slug: string, targetSlug: string): Promise<void> {
  return request<void>(
    `/documents/${encodeURIComponent(slug)}/references/${encodeURIComponent(targetSlug)}`,
    { method: 'DELETE' },
  )
}

export function reset(): Promise<ResetResult> {
  return request<ResetResult>('/reset', { method: 'POST' })
}

export function runQuery(cypher: string): Promise<Record<string, unknown>[]> {
  return request<Record<string, unknown>[]>('/query', {
    method: 'POST',
    body: JSON.stringify({ cypher }),
  })
}
```

- [ ] **Step 6: Run the tests**

Expected: 27 passed (21 existing + 6 new), `tsc -b` clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api
git commit -m "feat: typed client methods for every backend endpoint"
```

---

## Task 10: STORY-010 — document table

**Files:**
- Create: `frontend/src/views/DocumentTable.tsx`, `views/DocumentTable.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `listDocuments`, `DocumentOut`.
- Produces: default-exported `DocumentTable` mounted at `/documents`.

**Behaviour:** fetch on mount; render one row per document showing name, reference role, and reference count; filter client-side by name as the user types; resolve reference slugs to names from the same payload; surface a fetch failure.

- [ ] **Step 1: Write the failing test**

`frontend/src/views/DocumentTable.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut } from '../api/types'

const listDocuments = vi.fn()
vi.mock('../api/client', () => ({
  listDocuments: () => listDocuments(),
  ApiError: class extends Error {},
}))

import DocumentTable from './DocumentTable'

const documents: DocumentOut[] = [
  {
    slug: 'dodd-5000-01',
    name: 'DoDD 5000.01',
    reference_role: 'Root Reference',
    is_external: false,
    references: ['public-law-116-92'],
    referenced_by: [],
  },
  {
    slug: 'dodi-3115-14',
    name: 'DoDI 3115.14',
    reference_role: 'Sub-Reference',
    is_external: false,
    references: [],
    referenced_by: [],
  },
  {
    slug: 'public-law-116-92',
    name: 'Public Law 116-92',
    reference_role: null,
    is_external: true,
    references: [],
    referenced_by: ['dodd-5000-01'],
  },
]

afterEach(() => listDocuments.mockReset())

describe('DocumentTable', () => {
  it('renders a row per document with its name and reference role', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    await waitFor(() => expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument())
    expect(screen.getByText('Root Reference')).toBeInTheDocument()
    expect(screen.getAllByRole('row')).toHaveLength(documents.length + 1) // + header
  })

  it('shows the external fallback rather than an empty role cell', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    const row = await screen.findByRole('row', { name: /Public Law 116-92/ })
    expect(row).toHaveTextContent('External reference')
    expect(row.textContent).not.toMatch(/null/i)
  })

  it('resolves reference slugs to document names', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    const row = await screen.findByRole('row', { name: /DoDD 5000.01/ })
    expect(row).toHaveTextContent('Public Law 116-92')
    expect(row.textContent).not.toContain('public-law-116-92')
  })

  it('filters by name as the user types', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'DoDI')

    expect(screen.getByText('DoDI 3115.14')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 5000.01')).not.toBeInTheDocument()
  })

  it('filters case-insensitively', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'public law')

    expect(screen.getByText('Public Law 116-92')).toBeInTheDocument()
  })

  it('says so when a filter matches nothing', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'zzzz')

    expect(screen.getByText(/no documents match/i)).toBeInTheDocument()
  })

  it('surfaces a fetch failure', async () => {
    listDocuments.mockRejectedValue(new Error('backend down'))
    render(<DocumentTable />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })
})
```

- [ ] **Step 2: Run and confirm it fails**

Expected: `Failed to resolve import "./DocumentTable"`.

- [ ] **Step 3: Write the component**

`frontend/src/views/DocumentTable.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react'
import { listDocuments } from '../api/client'
import type { DocumentOut } from '../api/types'

export default function DocumentTable() {
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    let cancelled = false

    listDocuments()
      .then((result) => {
        if (!cancelled) setDocuments(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load documents.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  const namesBySlug = useMemo(() => {
    const names = new Map<string, string>()
    for (const document of documents ?? []) names.set(document.slug, document.name)
    return names
  }, [documents])

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return documents ?? []
    return (documents ?? []).filter((d) => d.name.toLowerCase().includes(needle))
  }, [documents, filter])

  if (error) return <div role="alert">Could not load documents: {error}</div>
  if (!documents) return <p>Loading documents…</p>

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Documents</h1>

      <input
        type="search"
        aria-label="Filter documents by name"
        placeholder="Filter by name…"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />

      <p>
        Showing {visible.length} of {documents.length}
      </p>

      {visible.length === 0 ? (
        <p>No documents match that filter.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Reference role</th>
              <th>References</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((document) => (
              <tr key={document.slug}>
                <td>{document.name}</td>
                <td>{document.reference_role ?? 'External reference'}</td>
                <td>
                  {document.references
                    .map((slug) => namesBySlug.get(slug) ?? slug)
                    .join(', ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Mount the route**

`frontend/src/App.tsx`:

```tsx
import { Route, Routes } from 'react-router-dom'
import DocumentTable from './views/DocumentTable'
import GraphExplorer from './views/GraphExplorer'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<GraphExplorer />} />
      <Route path="/documents" element={<DocumentTable />} />
    </Routes>
  )
}
```

- [ ] **Step 5: Run the tests and the build**

Expected: 34 passed, `tsc -b` clean.

- [ ] **Step 6: Look at the page**

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/documents
```

Report what you could and could not verify. There is no headless browser here — do not imply you saw it render.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: searchable document table at /documents"
```

---

## Task 11: Acceptance and documentation

**Files:**
- Create: `backend/tests/test_di1_complete.py`, `docs/sprints/sprint-02/plan.md`, `docs/sprints/sprint-02/review.md`
- Modify: `docs/specs/SPEC-001-di-1-policy-grapher.md`, `docs/specs/architecture.md`, `docs/planning/roadmap.md`, `docs/backlog/backlog.md`, `docs/backlog/epics/EPIC-001-di-1-end-to-end-feasibility.md`

- [ ] **Step 1: Write the acceptance test**

`backend/tests/test_di1_complete.py`:

```python
"""Every endpoint SPEC-001 names now exists."""

import pytest

pytestmark = pytest.mark.integration

SAMPLE = "dod_policy_references_08122026.csv"


def test_every_specified_endpoint_responds(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})

    assert client_with_graph.get("/health").status_code == 200
    assert client_with_graph.get("/graph").status_code == 200
    assert client_with_graph.get("/documents").status_code == 200
    assert client_with_graph.get("/documents/dodd-5000-01").status_code == 200
    assert client_with_graph.post(
        "/query", json={"cypher": "RETURN 1 AS one"}
    ).status_code == 200

    created = client_with_graph.post(
        "/documents", json={"name": "DoDD 9999.01", "reference_role": "Root Reference"}
    )
    assert created.status_code == 201
    slug = created.json()["slug"]

    assert client_with_graph.put(
        f"/documents/{slug}",
        json={"name": "DoDD 9999.01", "reference_role": "Sub-Reference"},
    ).status_code == 200
    assert client_with_graph.post(
        f"/documents/{slug}/references/dodd-5000-01"
    ).status_code == 204
    assert client_with_graph.delete(
        f"/documents/{slug}/references/dodd-5000-01"
    ).status_code == 204
    assert client_with_graph.delete(f"/documents/{slug}").status_code == 204
    assert client_with_graph.post("/reset").status_code == 200


def test_a_full_round_trip_leaves_the_graph_as_it_started(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    before = client_with_graph.get("/graph", params={"include_external": "true", "limit": 0}).json()

    created = client_with_graph.post(
        "/documents", json={"name": "Temporary Document", "reference_role": "Sub-Reference"}
    ).json()
    client_with_graph.post(f"/documents/{created['slug']}/references/dodd-5000-01")
    client_with_graph.delete(f"/documents/{created['slug']}")

    after = client_with_graph.get("/graph", params={"include_external": "true", "limit": 0}).json()
    assert after == before
```

- [ ] **Step 2: Run both suites**

```bash
cd backend && sg docker -c "uv run pytest -q"
sg docker -c "docker compose exec -T frontend npm test"
```

Expected: 111 backend, 34 frontend, output pristine.

- [ ] **Step 3: Verify from a cold start**

```bash
sg docker -c "docker compose down -v"
sg docker -c "docker compose up -d --build"
```

Then confirm, and put the verbatim output in the report:

```
curl -s localhost:5173/api/graph            -> returned_nodes 23, total_nodes 23, 72 edges
curl -s localhost:5173/api/documents        -> 438 entries
curl -s -X POST localhost:5173/api/query -H 'Content-Type: application/json' \
     -d '{"cypher":"MATCH (d:Document) RETURN count(d) AS total"}'   -> [{"total":438}]
curl -s -X POST localhost:5173/api/reset    -> {"nodes_deleted":438,"relationships_deleted":672}
```

- [ ] **Step 4: Update SPEC-001**

Add `GET /health` to the Ingest endpoint table — it is implemented, exercised by the client, and appears nowhere in the spec. In the Pydantic Models section, state that `references` and `referenced_by` carry slugs.

- [ ] **Step 5: Update `architecture.md`**

The backend Components row lists document CRUD, references, `/reset` and `/query` as "not built in DI-1"; the frontend row says the `/documents` table is not built. Both are now wrong. Describe the built system.

The two Known-weak-points bullets about `POST /query` and `GET /documents` were reworded into future tense on 2026-08-13 because those endpoints did not exist. **Return them to present tense** — both are now live, unauthenticated and unbounded, and ADR-004's acceptance is once again describing something real. Add the router structure to Components.

- [ ] **Step 6: Update `roadmap.md`**

It still says *"Nothing is built yet — the repo is specification and sample data only."* Replace the **Now** section: DI-1 is complete; the next milestone is the roadmap's existing **Next** block. Refresh *Last reviewed*.

- [ ] **Step 7: Update the backlog and epic**

Move STORY-005, 006, 027, 028, 008, 010 to Done with sprint `2`. Remove STORY-032 from Ideas — Task 3 delivered it — and record it as Done, sprint 2. Set EPIC-001 to `**Status:** Done — 18 of 18 stories`, and mark its six remaining rows Done. Refresh *Last reviewed*.

- [ ] **Step 8: Write the sprint 2 plan and review**

Create both from `docs/sprints/TEMPLATE-sprint/`. The plan records the committed six plus the refactor, and **states explicitly that ADR-004's three conditions — local-only, disposable data, Cypher-fluent trusted audience — were confirmed to hold at the time `POST /query` shipped**, because ADR-004 requires that check before the endpoint moves outward.

The review records that STORY-004 and STORY-015 were recognised as complete after sprint 1 closed, which is why sprint 1's review undercounts. Do not edit sprint 1's review — it is a frozen dated record.

- [ ] **Step 9: Update `velocity.md`**

Add the sprint 2 row. Counts, not points; no item carries an estimate.

- [ ] **Step 10: Commit**

```bash
git add backend/tests/test_di1_complete.py docs
git commit -m "test: DI-1 acceptance across every specified endpoint; sync docs"
```

---

## Self-Review

**Spec coverage.** Every section of the design maps to a task.

| Design section | Task |
| --- | --- |
| Router structure, `dependencies.py` | 1 |
| ADR-005 | 2 |
| STORY-032 type-check gate | 3 |
| `POST /reset`, counts from `clear_graph` | 4 |
| `DocumentOut`, read endpoints, slugs not names | 5 |
| `DocumentIn`, create/update/delete, ADR-005 slug rule, 409 vs contested slug, `PUT` on external | 6 |
| Reference edges, idempotency both ways, self-reference | 7 |
| `POST /query`, value coercion, `str()` fallback, unrestricted per ADR-004 | 8 |
| Nine client methods, 204 handling | 9 |
| Document table | 10 |
| Acceptance, SPEC-001 DoD now meetable, all seven doc updates | 11 |

**Placeholder scan.** No TBD, no "add error handling", no "similar to Task N". Every code step carries real code. Task 1 Step 6 uses `...  # unchanged` for two functions deliberately — the instruction is to *not* edit them, and reproducing forty lines verbatim invites accidental drift.

**Type consistency.** `DocumentOut` fields are identical in `models.py` (Task 5), `types.ts` (Task 9), and every test. `clear_graph`'s changed return type is consumed only in Task 4's route; its two existing callers ignore the return value and need no edit. `DocumentNotFoundError` is raised in Tasks 5, 6 and 7 and caught in each corresponding route. `_read`, `_write` and `_count` are defined once in Task 5 and reused in 6 and 7. `coerce` and `run_cypher` signatures match between `query.py` and its tests.

**Runtime semantics** — the pass my last plan lacked, added because every Important finding in the DI-1 review was a semantics defect the type-consistency pass could not see:

- *Transaction boundaries.* Every new write is a single statement, so no multi-statement atomicity problem arises. `create_document` performs two reads and a write non-atomically; two concurrent creates of the same name can both pass the check and the second hits `document_name_unique`, surfacing as a 500 rather than a 409. Single-user demo, so accepted — and noted here rather than discovered later.
- *Aggregation grouping.* `DOCUMENT_FIELDS` uses two sequential `OPTIONAL MATCH` + `collect` stages. The second `WITH` carries `references` through unchanged, so the outgoing list cannot be multiplied by the incoming match — the mistake that produced the DI-1 review's degree double-count. `collect` drops nulls, so a document with no edges yields `[]`, not `[null]`.
- *Parameter precedence.* `add_reference` checks self-reference before existence, so `x -> x` is 400 even for an unknown slug. Stated in Task 7 so it is a decision, not an accident.
- *Route ordering.* `/documents/{slug}` and `/documents/{slug}/references/{target_slug}` cannot shadow each other — different segment counts. `@router.get("")` with a prefix serves `/documents` without a redirect; `@router.get("/")` would not.
- *Exception hierarchy.* `NameConflictError`, `NameMismatchError`, `ExternalDocumentError` and `SelfReferenceError` all subclass `ValueError`; every handler catches the specific class, never `ValueError`, so no ordering hazard.
- *Serialisation.* `coerce` checks `Node` and `Relationship` before `dict` — neo4j entities are `Mapping`s and would otherwise be caught by a dict branch and lose their labels.

**One known gap, stated rather than hidden.** Task 1's `test_routers.py` is a characterisation test: it passes before the refactor as well as after. That is the point — it pins the route table so the move cannot silently drop or duplicate an endpoint — but it does not follow red-green, and Task 1 Step 2 says so explicitly rather than dressing a green run up as a failing one.
