# Backlog

*Living document — edit in place. Last reviewed: 2026-08-13*

Ordered by priority: the top row is the next thing to pick up. See
[README](README.md) for how items move through this list, and
[CONVENTIONS](../CONVENTIONS.md) for when an item earns its own file.

All items below are derived from [SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md) and
the MVP definition of done in the [vision](../planning/vision.md).

## Ready

Refined, estimated, and pickable right now.

**TODO:** No item carries an estimate — the team hasn't sized these, and the
[Definition of Ready](README.md#definition-of-ready) requires it. Strictly these are
specified but not yet Ready. Size them at the first planning session and fill the column in.

| ID | Item | Epic | Est. | Notes |
| --- | --- | --- | --- | --- |
| STORY-004 | Ingest rejects a malformed CSV with a clear error instead of a stack trace | EPIC-001 | — | Wrong columns, unparseable `References`, missing file, traversal attempt. Not in the original spec — `ast.literal_eval` raises on real-world input |
| STORY-005 | A user can list all documents and read one with what it cites and what cites it | EPIC-001 | — | `GET /documents`, `GET /documents/{slug}` returning `references` and `referenced_by` |
| STORY-006 | A user can create, update, and delete documents through the API | EPIC-001 | — | `POST` / `PUT` / `DELETE /documents/{slug}`; `PUT` updates `reference_role` only and 400s on a name mismatch |
| STORY-027 | A user can add and remove a reference between two documents | EPIC-001 | — | `POST`/`DELETE /documents/{slug}/references/{target_slug}`. Closes the gap where edges were immutable after ingest |
| STORY-028 | An operator can wipe the graph and start clean | EPIC-001 | — | `POST /reset`. Ingest is additive and never removes, so this is how the graph is made to match a changed file |
| STORY-008 | An agent can run a raw Cypher query against the graph | EPIC-001 | — | `POST /query`, unrestricted in DI-1 by decision — [ADR-004](../specs/adr/ADR-004-unrestricted-cypher-in-di-1.md). Local-only |
| STORY-010 | A user can browse and filter the document table by name | EPIC-001 | — | Route `/documents`; client-side filter; shows name, reference role, references |

## Refining

Understood well enough to discuss, not yet ready to start.

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| ~~STORY-013~~ | ~~Referenced documents that aren't in the corpus are distinguishable~~ | — | **Superseded by STORY-026.** Resolved by [ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md); ID retained per [CONVENTIONS](../CONVENTIONS.md) |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | — | MVP DoD item; broader than STORY-010's table filter. "ID" is the slug from STORY-025 |
| STORY-015 | The rendered graph is bounded by a configurable cap, and says when it truncated | — | `GRAPH_RENDER_CAP` (default 300) with `?limit=` override; deterministic truncation; `truncated` / `total_nodes` surfaced in the UI. Now specified — promote to Ready once estimated |
| STORY-031 | Near-duplicate document names are reconciled | — | Ingest flags them (STORY-003); nothing merges them. Real entity resolution — deliberately out of DI-1 |
| STORY-016 | Ingestion accepts PDF, DOCX, and XLSX | — | MVP DoD item and the largest scope jump past DI-1 — extraction, not parsing. Likely an epic of its own |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | — | The "corpus management" MVP item; needs a decision on storing document text |

## Ideas

Unrefined. No commitment implied.

| ID | Item | Notes |
| --- | --- | --- |
| STORY-019 | Authentication on the API | Explicitly out of DI-1 scope; a prerequisite for any shared deployment |
| STORY-020 | Model policy points as nodes rather than whole documents | The Policy Concierge direction in the [vision](../planning/vision.md); a schema migration |
| STORY-021 | Capture applicable entities and enforcement ownership as graph relationships | Same — new labels and relationship types |
| STORY-023 | A user can ask a question in natural language and get graph results | LLM constructs the Cypher and calls `POST /query`. Gated on the schema settling and on STORY-019 (auth) — see [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) |
| STORY-024 | `POST /query` constrains what a generated query may do | Read-only enforcement, timeouts, result caps. A human at a demo is a benign caller; a generator isn't |
| STORY-032 | A TypeScript error fails the frontend test command | `npm test` runs vitest, which transpiles without type-checking; `tsc -b` runs only under `npm run build`, which no gate invokes. A type error can pass the suite and reach a commit — one did during the graph-explorer work and was caught only by running the build by hand |
| STORY-033 | Linting runs over both backend and frontend | Neither is configured (no `[tool.ruff]`, no eslint), so unused imports and dead code accumulate unflagged. Several were left deliberately unfixed in sprint 1 on the grounds that a batch pass would be cheaper than hand-picking |

## Done

Closed items, most recent first. Trim to the last two sprints — older history lives in
sprint reviews.

| ID | Item | Sprint |
| --- | --- | --- |
| STORY-012 | The sample DoD corpus loads and renders end to end | 1 |
| STORY-030 | Integration tests run against a real, disposable Neo4j | 1 |
| STORY-029 | The stack comes up with the sample corpus already loaded | 1 |
| STORY-011 | The frontend talks to the backend through one typed API client | 1 |
| STORY-009 | A user can see the corpus as a force-directed graph, click a node, and expand its external references | 1 |
| STORY-007 | The UI can fetch a legible graph in one call | 1 |
| STORY-026 | External documents are distinguishable from corpus documents in the graph | 1 |
| STORY-003 | A CSV of documents and references becomes a graph, and re-ingesting it changes nothing | 1 |
| STORY-025 | Every document gets a stable, URL-safe slug that survives re-ingest | 1 |
| STORY-002 | Backend connects to Neo4j and enforces unique constraints on `slug` and `name` | 1 |
| STORY-001 | A developer can bring the full stack up with one command | 1 |
