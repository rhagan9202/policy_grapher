# Sprint 1 — Review

**Date:** 2026-08-13

*Dated record — a snapshot of what happened.*

## Against the goal

Goal was: Ingest the sample DoD corpus and see it rendered as a navigable graph — the DI-1
spine working end to end on one machine.

Met. `docker compose up` brings up `neo4j`, `backend`, and `frontend`; the backend
auto-ingests the sample corpus into an empty database at startup; `GET /graph` serves the
23-document corpus view (72 edges) by default, `?include_external=true` exposes the full
438-node reference graph behind a 300-node render cap, and `?limit=0` returns it uncapped
(672 edges). The React force-directed explorer at `/` renders that view, shows a clicked
node's name and reference role, and expands external neighbours on click. All ten committed
stories shipped, plus STORY-030 (below).

## Completed

| ID | Item | Est. |
| --- | --- | --- |
| STORY-001 | A developer can bring the full stack up with one command | — |
| STORY-002 | Backend connects to Neo4j and enforces unique constraints on `slug` and `name` | — |
| STORY-025 | Every document gets a stable, URL-safe slug that survives re-ingest | — |
| STORY-003 | A CSV of documents and references becomes a graph, and re-ingesting it changes nothing | — |
| STORY-026 | External documents are distinguishable from corpus documents in the graph | — |
| STORY-007 | The UI can fetch a legible graph in one call | — |
| STORY-011 | The frontend talks to the backend through one typed API client | — |
| STORY-009 | A user can see the corpus as a force-directed graph, click a node, and expand its external references | — |
| STORY-029 | The stack comes up with the sample corpus already loaded | — |
| STORY-012 | The sample DoD corpus loads and renders end to end | — |
| STORY-030 | Integration tests run against a real, disposable Neo4j | — |

**Delivered:** 11 of 10 committed. STORY-030 was flagged in the plan's risks as
deliberately uncommitted, with the call deferred to review: pull it in, or close the sprint
with the "tests written and passing" gate unmet for everything above it. It was pulled in —
every integration test in the suite runs against a `testcontainers`-managed, disposable
Neo4j rather than a mock.

## Not completed

Each with where it went — back to the backlog, cancelled, or split.

| ID | Item | Why | Disposition |
| --- | --- | --- | --- |
| — | Nothing committed was left incomplete. | — | — |

None of the stretch items (STORY-005, STORY-010, STORY-004) were picked up — committed work
did not finish early enough to reach them. They remain in the backlog's Ready column.

## Demo notes and feedback

**The sample corpus collides on slugs twice, contradicting ADR-003's assumption that it
might not collide at all.** `POST /ingest` against the real 23-row corpus produces two
pairs of names that normalise to the same base slug. Because the collision path therefore
runs on every ingest of the real data, not just in a synthetic unit test, the plan's risk
note — "the sample corpus may not collide at all, so the collision branch needs a
deliberate test rather than incidental coverage" — did not materialise. The branch gets
exercised for free.

**The collision rule needed an order-independence fix to honour ADR-003's stated promise
that slugs are a pure function of the name.** The first implementation gave the base slug
to whichever contender was processed first and suffixed only the second arrival, which
makes a document's slug depend on CSV row order or ingest order — silently violating the
ADR's stability guarantee. `assign_slugs` now resolves each contested base slug over the
full set of names being assigned at once, and suffixes every contender, not just the
second. **An amending ADR is owed before STORY-006 (document CRUD) lands**: ADR-003
describes slug assignment as a per-name function, but it is actually a function of the
whole batch, and a document created later via `POST /documents` has no batch to join — it
cannot retroactively re-slug a document that already holds an uncontested base slug it now
collides with.

**Python 3.14 was a non-issue.** The plan's top-rated risk — that base image availability
and library support for a version this recent would cost a lost day — did not happen. The
full dependency set (FastAPI, Pydantic v2, the `neo4j` driver, pytest, `testcontainers`)
resolved and imported on the first attempt.
