# Backlog

*Living document — edit in place. Last reviewed: 2026-08-13*

Ordered by priority: the top row is the next thing to pick up. See
[README](README.md) for how items move through this list, and
[CONVENTIONS](../CONVENTIONS.md) for when an item earns its own file.

All items below are derived from [SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md) and
the MVP definition of done in the [vision](../planning/vision.md).

## Ready

Refined, estimated, and pickable right now.

Nothing. EPIC-001 closed on 2026-08-13 and took the last of the Ready items with it; the
next milestone's work is still in [Refining](#refining) and [Ideas](#ideas). The estimate
column stays unfilled — no item has ever carried one, so the
[Definition of Ready](README.md#definition-of-ready) is not yet being met in practice. Size
items at the next planning session before promoting any of them here.

| ID | Item | Epic | Est. | Notes |
| --- | --- | --- | --- | --- |

## Refining

Understood well enough to discuss, not yet ready to start.

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| ~~STORY-013~~ | ~~Referenced documents that aren't in the corpus are distinguishable~~ | — | **Superseded by STORY-026.** Resolved by [ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md); ID retained per [CONVENTIONS](../CONVENTIONS.md) |
| STORY-038 | Creating a document through the API is one transaction | — | `create_document` runs four separate auto-commit statements — `CREATE_DOCUMENT`, then `MERGE_SOURCE`, `DESCRIBES` and `REFRESH_EXTERNAL` — where both ingest paths run their writes inside one `session.execute_write`. A crash after the first leaves a document with no provenance **and** no `:External` label, which nothing re-refreshes; the next manifest that cites that name then silently demotes it, so it disappears from the default `/graph` view. Found by STORY-037's final review and deferred there. The fix follows `ingest_document`'s shape: resolve the slug and the name check first (both are reads, and `driver.execute_query` cannot run inside a write transaction), then commit the four writes together. Needs a `session.execute_write` helper `documents.py` does not have yet |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | — | MVP DoD item; broader than STORY-010's table filter. "ID" is the slug from STORY-025 |
| STORY-031 | Near-duplicate document names are reconciled | — | Ingest flags them (STORY-003); nothing merges them. Real entity resolution — deliberately out of DI-1 |
| STORY-035 | Ingestion accepts a DOCX issuance | — | Same `extract_document` protocol as STORY-016, own extraction rules. Blocked: no DOCX sample exists to design against. Likely easier than PDF — `python-docx` exposes heading styles, so locating the references section stops being the risky stage |
| STORY-036 | Ingestion accepts an XLSX manifest | — | The *manifest* path alongside CSV, not document extraction — a sibling of `sources/manifest.py`, far smaller than either extraction story |
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

## Done

Closed items, most recent first. Trim to the last two sprints — older history lives in
sprint reviews.

| ID | Item | Sprint |
| --- | --- | --- |
| STORY-037 | A CSV re-ingest stops demoting a PDF-ingested document to `:External` | 3 |
| STORY-016 | Ingestion accepts a PDF issuance and extracts its references | 3 |
| STORY-034 | Relational facts move off `Document` and onto typed edges | 3 |
| STORY-033 | Linting runs over both backend and frontend | 3 |
| STORY-010 | A user can browse and filter the document table by name | 2 |
| STORY-008 | An agent can run a raw Cypher query against the graph | 2 |
| STORY-027 | A user can add and remove a reference between two documents | 2 |
| STORY-006 | A user can create, update, and delete documents through the API | 2 |
| STORY-005 | A user can list all documents and read one with what it cites and what cites it | 2 |
| STORY-028 | An operator can wipe the graph and start clean | 2 |
| STORY-032 | A TypeScript error fails the frontend test command | 2 |
| STORY-015 | The rendered graph is bounded by a configurable cap, and says when it truncated | 1 |
| STORY-004 | Ingest rejects a malformed CSV with a clear error instead of a stack trace | 1 |
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
