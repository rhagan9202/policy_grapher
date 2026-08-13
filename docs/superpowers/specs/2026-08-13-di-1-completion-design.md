# DI-1 Completion — Design

**Date:** 2026-08-13 · **Status:** Approved, ready for an implementation plan

Design for finishing every endpoint SPEC-001 names, closing EPIC-001 at 18 of 18 stories.

This is a *design* document, not a new spec: [SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md)
already specifies all of this behaviour. What follows is how to build the remaining half,
plus the decisions SPEC-001 leaves open. It lives beside the DI-1 implementation plan rather
than in `docs/specs/` for that reason — nothing here supersedes or extends SPEC-001's
behavioural contract, and no new `SPEC-NNN` is warranted.

## Goal

Sprint 1 delivered the DI-1 spine: CSV ingest, the corpus-first graph endpoint, auto-ingest,
the compose stack, and the graph explorer. Twelve of eighteen EPIC-001 stories are done.

This work delivers the remaining six, after which every endpoint in SPEC-001 exists and the
spec's Definition of Done becomes meetable for the first time.

| Story | Delivers |
| --- | --- |
| STORY-005 | `GET /documents`, `GET /documents/{slug}` |
| STORY-006 | `POST` / `PUT` / `DELETE /documents` |
| STORY-027 | `POST` / `DELETE /documents/{slug}/references/{target_slug}` |
| STORY-028 | `POST /reset` |
| STORY-008 | `POST /query` |
| STORY-010 | Document table at `/documents` |

## What is already true

Established by sprint 1 and verified against the running system:

- 71 backend tests and 21 frontend tests pass. 31 of the backend tests run without Docker.
- The graph holds 438 documents — 23 corpus, 415 external — and 672 `REFERENCES` edges.
- `db.py` already exports `clear_graph`, so `POST /reset` is a thin route over existing code.
- `models.py` defines `IngestRequest`, `IngestResult`, `GraphNode`, `GraphEdge`, `GraphOut`.
  `DocumentIn` and `DocumentOut` do not exist yet.
- `main.py` registers exactly three routes and reads `app.state` through the module-global
  `app` — a deferred finding from the DI-1 whole-branch review.
- Integration tests share a session-scoped Neo4j container with the `clean_graph` and
  `client_with_graph` fixtures in `backend/tests/conftest.py`.

## Decisions taken

Three decisions were settled before design and are binding on the plan.

**Scope is SPEC-001, not the MVP bar.** Multi-format ingestion, corpus management, and
search stay in the roadmap's *Next*. The six stories above are the whole of it.

**A newly created document that contests an existing slug takes the suffix; the incumbent
keeps its bare slug.** No URL ever changes out from under a holder. The accepted cost is
that slug assignment stops being a pure function of the name set for incrementally created
documents — ingest-time assignment stays pure, but a reset-and-reingest can then produce
different slugs than incremental creation did. Recorded in ADR-005.

**`POST /query` ships unrestricted, exactly as ADR-004 describes** — no read-only
enforcement, no timeout, no row cap. ADR-004's three conditions (local-only, disposable
data, Cypher-fluent trusted audience) were confirmed to still hold. The sprint plan records
that confirmation, because ADR-004 requires the decision be revisited before shipping if any
condition lapses.

## Architecture

Twelve endpoints across four concerns is past the point where a single route module holds
together, so routes split into FastAPI routers and `main.py` reduces to assembly.

```
backend/src/policy_grapher/
  main.py                 app assembly, lifespan, router registration — nothing else
  dependencies.py         NEW — get_driver / get_settings from request.app.state
  routers/
    __init__.py           NEW
    admin.py              NEW — GET /health · POST /ingest · POST /reset
    documents.py          NEW — 5 document routes + 2 reference routes
    graph.py              NEW — GET /graph · POST /query
  documents.py            NEW — all document and reference Cypher
  query.py                NEW — run_cypher + value coercion
  models.py               + DocumentIn, DocumentOut
  db.py                   unchanged
  graph.py                unchanged
  ingest.py, slugs.py, csv_source.py, config.py   unchanged
```

`/query` sits in the graph router because it is a graph read, and grouping it there keeps its
ADR-004 caveat beside the thing it reads.

Domain modules preserve the layering the DI-1 review praised: `documents.py` holds Cypher and
imports nothing from FastAPI, exactly as `graph.py` does today. `query.py` is small, but
giving the passthrough a named unit keeps "no Cypher in routes" true without exception.

Routers have no module-global `app`, so they resolve state through `request.app.state` via
two injectable dependencies. This closes the deferred review finding as a side effect rather
than as separate work.

## Endpoint contracts

| Endpoint | Success | Errors |
| --- | --- | --- |
| `GET /documents` | `200` `list[DocumentOut]`, all 438, ordered by slug ascending | — |
| `GET /documents/{slug}` | `200` `DocumentOut` | `404` unknown slug |
| `POST /documents` | `201` `DocumentOut` | `409` name exists · `422` empty name or role |
| `PUT /documents/{slug}` | `200` `DocumentOut` | `404` · `400` body name mismatch · `400` target is `:External` |
| `DELETE /documents/{slug}` | `204`, `DETACH DELETE` | `404` |
| `POST /documents/{slug}/references/{target_slug}` | `204`, idempotent `MERGE` | `404` either endpoint · `400` self-reference |
| `DELETE /documents/{slug}/references/{target_slug}` | `204`, idempotent | `404` either endpoint |
| `POST /reset` | `200` `{nodes_deleted, relationships_deleted}` | — |
| `POST /query` | `200` `list[dict]` | `400` Cypher error, driver message passed through |

### Models

```python
class DocumentIn(BaseModel):
    name: str = Field(min_length=1)
    reference_role: str = Field(min_length=1)

class DocumentOut(BaseModel):
    slug: str
    name: str
    reference_role: str | None
    is_external: bool
    references: list[str]       # slugs this document cites
    referenced_by: list[str]    # slugs that cite this document
```

`references` and `referenced_by` carry **slugs, not names**. SPEC-001 types them `list[str]`
without saying which. Slugs are correct because documents are addressed by slug everywhere
else, `DocumentOut` already carries `name` for display, and names would leave a client unable
to navigate to a reference — there is no name-to-slug lookup endpoint. STORY-010's table
resolves slugs to names client-side from the same `GET /documents` payload, which already
contains every document.

### Decisions SPEC-001 leaves open

- **`PUT` on an `:External` document is `400`.** External documents have no `reference_role`
  by definition ([ADR-002](../../specs/adr/ADR-002-external-references-and-corpus-first-graph.md)),
  and setting one recreates the both-external-and-role state that Task 5 of the DI-1 plan
  fixed. Promoting an external document to corpus is an ingest concern, not an edit.
- **`POST /documents` always creates a corpus document.** `DocumentIn` requires
  `reference_role`, so no API path creates an `:External` node — correct, since external
  means "cited but absent from the corpus."
- **A duplicate name is `409`. A contested *slug* is not.** These are different cases and
  must not be conflated. Posting a name that already exists verbatim is a conflict and is
  rejected. Posting a *different* name that happens to normalise to an existing document's
  base slug succeeds with `201`, and the new document takes the `-<sha8>` suffix per ADR-005
  — the incumbent is untouched. Today the first case escapes as an unhandled error, which is
  the deferred finding from the DI-1 review; the second case is currently a `500`.
- **`DELETE` works on external documents too.** They are `Document` nodes and the endpoint
  is defined over documents. Deleting one removes it and its edges; a later ingest that
  cites it recreates it.
- **Reference endpoints are idempotent in both directions.** `DELETE` on an absent edge
  returns `204`. The contract is "this edge does not exist afterwards," not "an edge was
  removed."
- **`/reset` returns counts** rather than `204`. More useful at a demo, and it gives tests
  something to assert beyond the absence of an exception. Auto-ingest does not re-trigger:
  it runs at startup only, which `test_startup.py` already guards.

### `POST /query` value coercion

The highest-risk detail in this design, and absent from SPEC-001.

`MATCH (n) RETURN n LIMIT 5` — the first thing a Cypher-fluent user types, and the exact
audience [ADR-001](../../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) assumes —
returns neo4j `Node` objects. FastAPI cannot serialise them, so the endpoint would return
`500` on the demo's opening move.

`query.py` coerces driver values before returning:

| Driver value | Serialised as |
| --- | --- |
| `Node` | `{"labels": [...], "properties": {...}}` |
| `Relationship` | `{"type": "...", "properties": {...}}` |
| `Path` | `{"nodes": [...], "relationships": [...]}` using the rules above |
| `list` / `dict` | coerced element-wise, recursively |
| `str`, `int`, `float`, `bool`, `None` | passed through unchanged |
| anything else | `str(value)` |

The `str()` fallback is not decoration. This schema stores only strings, so no *stored* value
can be temporal or spatial — but `/query` accepts arbitrary Cypher, and `RETURN datetime()`
or `RETURN point({x: 1, y: 2})` are both valid and both return types FastAPI cannot
serialise. Falling back to `str()` keeps the endpoint from returning `500` on a query that
touches no data at all.

## Sequencing

| # | Work | Notes |
| --- | --- | --- |
| 1 | Router refactor | Pure restructure, no behaviour change. All 71 backend tests must stay green — that is the entire verification. Goes first so the nine new routes are never written into `main.py` and then moved. |
| 2 | ADR-005 | Docs only. Gates step 6. |
| 3 | STORY-032 | `npm test` runs `tsc -b` first. Cheap, and step 10 is the largest frontend change yet. |
| 4 | STORY-028 | `POST /reset`. Smallest story; `clear_graph` exists. |
| 5 | STORY-005 | Introduces `documents.py` and `DocumentOut`. |
| 6 | STORY-006 | Create, update, delete. Needs ADR-005. |
| 7 | STORY-027 | Reference edges. Same module as 5 and 6. |
| 8 | STORY-008 | `POST /query` and the coercion above. Independent of 4–7. |
| 9 | Client methods | Nine typed wrappers, completing STORY-011's "every endpoint". |
| 10 | STORY-010 | Document table at `/documents`. Needs 5 and 9. |

STORY-032 is not one of the six committed stories. It is included because the frontend has no
type-check gate at all — `npm test` transpiles without checking types, and `tsc -b` runs only
under `npm run build`, which no gate invokes. A type error reached a commit during the DI-1
graph-explorer work and was caught only by running the build by hand.

## ADR-005 — amending ADR-003

Recorded as owed since sprint 1, and required before step 6. It amends rather than supersedes:
ADR-003 stands. Three decisions:

1. **Slug assignment at ingest is a function of the whole name set**, not of each name alone.
   When a base slug is contested, every contender takes a `-<sha8>` suffix. This is what
   ADR-003's literal rule — suffix the second arrival — could not deliver, because that rule
   is ingest-order dependent and so contradicts ADR-003's own stability promise.
2. **At incremental creation the incumbent keeps its bare slug and the newcomer takes the
   suffix.** The consequence, stated plainly: ingest-time and create-time assignment can
   diverge, so a reset-and-reingest may produce different slugs than incremental creation
   did. URL stability for existing documents was judged worth that.
3. **A suffixed slug can reach 89 characters**, against ADR-003's stated 80, because the
   suffix is appended after truncation. Nothing enforces 80 anywhere; the ADR records the
   real bound.

## Verification

Unchanged in shape from DI-1.

- Pure logic — the `/query` coercion, slug rules — unit-tested with no Docker. The coercion
  gets its own tests for `Node`, `Relationship`, `Path`, nested collections, scalars, and a
  type with no JSON representation, asserting the `str()` fallback rather than a `500`.
- Everything touching Cypher is integration-tested against the disposable Neo4j container
  through the existing `clean_graph` and `client_with_graph` fixtures.
- Frontend keeps the mocked-library pattern from `GraphExplorer.test.tsx`.
- The router refactor's verification is that all 71 existing backend tests pass unchanged.

**SPEC-001's Definition of Done becomes fully meetable.** Its final minimum-coverage item —
*"`PUT` with a mismatched name returns 400"* — currently has no endpoint to exercise. Five of
its six items are met today; this work makes it six.

## Documentation this work must move

- **SPEC-001** — add `GET /health`, which is implemented, exercised by the client, and
  appears nowhere in the spec's endpoint tables. Pin `references` / `referenced_by` as slugs.
- **`specs/architecture.md`** — Components table: the backend row currently lists document
  CRUD, references, `/reset` and `/query` as "not built in DI-1"; the frontend row says the
  `/documents` table is not built. Both become wrong. The two Known-weak-points bullets about
  `POST /query` and `GET /documents`, reworded into future tense on 2026-08-13, return to
  present tense — those endpoints become genuinely live, unauthenticated and unbounded.
- **`planning/roadmap.md`** — currently states *"Nothing is built yet — the repo is
  specification and sample data only."* False since sprint 1 and false regardless of this
  work; fix it either way.
- **`backlog/backlog.md`** — six stories to Done, sprint 2.
- **`backlog/epics/EPIC-001-di-1-end-to-end-feasibility.md`** — 18 of 18, status Done.
- **`sprints/sprint-02/plan.md`** — new, recording the commitment and ADR-004's re-affirmed
  conditions.
- **`sprints/sprint-01/review.md`** — left alone. A dated document, frozen, accurate when
  written. Sprint 2's review is where the late recognition of STORY-004 and STORY-015 belongs.

## Out of scope

STORY-014 (search by name or ID), STORY-016 (PDF/DOCX/XLSX ingestion), STORY-017 (corpus
management), STORY-024 (query constraints), STORY-019 (authentication), STORY-031 (entity
resolution), STORY-033 (linting).

Also unchanged: the twelve cosmetic minors deferred from the DI-1 review, and the causal
bookmarking gap in `ingest.py` — real only against a Neo4j cluster, which ADR-004 forbids
without revisiting.
