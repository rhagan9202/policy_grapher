# Backlog

*Living document — edit in place. Last reviewed: 2026-08-21*

Ordered by priority: the top row is the next thing to pick up. See
[README](README.md) for how items move through this list, and
[CONVENTIONS](../CONVENTIONS.md) for when an item earns its own file.

All items below are derived from [SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md) and
the MVP definition of done in the [vision](../planning/vision.md).

## Ready

Refined, estimated, and pickable right now.

The tech-debt surge, planned 2026-08-21 and sequenced across sprints 3–5 — see the
[roadmap](../planning/roadmap.md#the-tech-debt-surge). **Every row below carries a size**,
using the [t-shirt scale](README.md#estimation) adopted at the same session, so the
[Definition of Ready](README.md#definition-of-ready) is met here for the first time.

Sprint 3 closed on 2026-08-21 with all seven of its items delivered; they have moved to
[Done](#done). Sprint 4's spine, STORY-048, has since landed and moved there too: `POST
/documents/{slug}/versions/{version_id}/rebuild` queues a rebuild onto a Redis-backed RQ
queue that a `worker` service drains, and `GET /rebuilds/{run_id}` reports its progress —
so `rebuild_derived`, `embed_chunks`, `CachedExtractor` and `GraphCacheStore` all have a
caller in the running application now, and Triage, Review and Ask can be filled without
running Python by hand. What remains is the rest of sprint 4, and sprint 5.

| ID | Item | Epic | Est. | Sprint | Notes |
| --- | --- | --- | --- | --- | --- |
| STORY-051 | Both suites run on a check nobody has to remember | — | M | 4 | [architecture.md](../specs/architecture.md) states plainly that there is no CI, and the [Definition of Done](README.md#definition-of-done) has carried a TODO about it since it was written. Every check currently depends on a person choosing to run `uv run pytest` and `npm test`. The surge is the point at which that stops being tenable: it will close a dozen defects, and nothing would catch the thirteenth |
| STORY-052 | The backend image carries only what it needs to run | — | M | 4 | Adding `sentence-transformers` for [ADR-016](../specs/adr/ADR-016-embeddings-are-a-port.md) pulled `torch`, `transformers` and `scikit-learn`: the backend virtualenv measures **4.9 GB** and importing the library costs ~9s. `LocalEmbedder` already imports lazily so the default `null` configuration pays neither cost at runtime, but the image carries the weight regardless, against a vision constraint of a stack that comes up on one command. Options: an optional dependency group, a multi-stage build, or a lighter static-embedding library behind the same port — the port exists precisely to keep that swap small |
| STORY-055 | Extraction recognises the modality this corpus actually uses | — | M | 6 | `Modality` is closed to `SHALL \| MUST \| SHOULD \| MAY`. Counted across the seven sample PDFs, **`will` appears 458 times against `shall` 93** — and it is generational, not incidental: the 2003 edition of DoDD 5000.01 uses `shall` 92 times and `must` never, while its 2020 re-issue uses `shall` zero times and `will` 44. DoD's plain-language drafting replaced the directive `shall` with `will`, so on five of the seven samples an extractor obeying the enum can only report a minority of the document's duties. ADR-013 records this as a known limitation and names widening the enum as the first thing to consider next. Needs its own ratchet leg, and a superseding ADR |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | — | M | 5 | The "corpus management" MVP item. **No longer blocked:** the decision it was waiting on is made and built — [ADR-012](../specs/adr/ADR-012-chunks-follow-sections.md) stores text as `:Chunk` nodes and `GET /documents/{slug}/chunks` serves them, ordered, with `page` and `section_path`. What is missing is only the front end: `api/client.ts` has no function for that route at all, so nothing in the UI can read a document's text — confirmed by the 2026-08-21 UI audit. Needs a `listChunks` client function and a document-detail view; `GET /documents/{slug}/versions` (already wired for STORY-040) gives the edition picker |
| STORY-042 | A reviewer can work through the whole queue, not just its head | — | M | 5 | `Review.tsx` fetches the queue but renders `queue[0]` only, with Approve and Reject as the only actions. A proposal the reviewer cannot judge — needing a colleague, or a document they do not have — blocks every proposal behind it, because the only way to move on is to record a verdict, and [ADR-014](../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md) makes a verdict permanent and replayed on every rebuild. Wants a skip (client-side, recording nothing) or a list view. Note that "skip" must not become a third verdict: the decision vocabulary is closed on purpose |
| STORY-043 | A user can ingest a document from the UI | — | M | 5 | `POST /ingest` has existed since DI-1 and `api/client.ts` has exposed `ingest()` since then; nothing calls it. Loading the corpus is currently a `curl` command or the startup auto-ingest, which means the person the tool is for cannot add a document to it. One of nine client functions with no UI caller as of the 2026-08-21 audit (DI-1 shipped 2 of 11 used; DI-2 phase 6 reached 7 of 16) |
| STORY-044 | A user can create, delete and cross-reference documents from the UI | — | L | 5 | `createDocument`, `deleteDocument`, `getDocument`, `addReference` and `removeReference` are all built, tested and unreachable — the API has supported corpus editing since STORY-026 and no screen offers it. Depends on [STORY-038](#refining) for `createDocument` to be transactional first, or the UI will expose the partial-write bug that story describes to real users |
| STORY-046 | A user can empty the graph from the UI | — | S | 5 | `POST /reset` and the `reset()` client function are both built and unreachable. Destructive, so it needs a confirmation step and a clear statement of what it deletes — and note it does *not* clear the vector index, which `ensure_vector_index` rebuilds on the next embed precisely because [ADR-016](../specs/adr/ADR-016-embeddings-are-a-port.md) treats a reset-orphaned index as the failure it is |

## Refining

Understood well enough to discuss, not yet ready to start.

| ID | Item | Epic | Notes |
| --- | --- | --- | --- |
| ~~STORY-013~~ | ~~Referenced documents that aren't in the corpus are distinguishable~~ | — | **Superseded by STORY-026.** Resolved by [ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md); ID retained per [CONVENTIONS](../CONVENTIONS.md) |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | — | MVP DoD item; broader than STORY-010's table filter. "ID" is the slug from STORY-025 |
| STORY-031 | Near-duplicate document names are reconciled | — | Ingest flags them (STORY-003); nothing merges them. Real entity resolution — deliberately out of DI-1 |
| STORY-035 | Ingestion accepts a DOCX issuance | — | Same `extract_document` protocol as STORY-016, own extraction rules. Blocked: no DOCX sample exists to design against. Likely easier than PDF — `python-docx` exposes heading styles, so locating the references section stops being the risky stage |
| STORY-036 | Ingestion accepts an XLSX manifest | — | The *manifest* path alongside CSV, not document extraction — a sibling of `sources/manifest.py`, far smaller than either extraction story |
| STORY-047 | A reissued document's edits are recognised as edits, not as wholesale replacement | — | Diffing the 2018 and 2020 editions of DoDD 5000.01 through the live stack produced **0 MODIFIED, 11 ADDED, 80 REMOVED**. That is [ADR-015](../specs/adr/ADR-015-changes-are-detected-and-ranked.md)'s documented fallback behaving exactly as designed — the two editions are structurally rewritten, so no `section_path` held exactly one unmatched obligation on each side and the section-based pairing never fired — but the result reads to a reviewer as "the whole document was replaced", which is the least actionable form the answer can take. Needs a second matching pass for obligations that moved between sections. See [STORY-047](stories/STORY-047-reissues-read-as-replacement.md) |

## Ideas

Unrefined. No commitment implied.

| ID | Item | Notes |
| --- | --- | --- |
| STORY-020 | Model policy points as nodes rather than whole documents | The Policy Concierge direction in the [vision](../planning/vision.md); a schema migration |
| STORY-021 | Capture applicable entities and enforcement ownership as graph relationships | Same — new labels and relationship types |
| STORY-023 | A user can ask a question in natural language and get graph results | LLM constructs the Cypher and calls `POST /query`. The two gates it carried are now half-cleared: STORY-019 (auth) and STORY-024 (query constraints) have landed, so only the schema settling remains — see [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md), superseding [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) |
| STORY-045 | A user can run a bounded Cypher query from the UI | `POST /query` and `runQuery()` are built and unreachable. Deliberately parked in Ideas rather than Refining: [ADR-008](../specs/adr/ADR-008-authenticated-non-cypher-audience.md) superseded [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) precisely to stop assuming the audience writes Cypher, so putting a query box in front of them argues against a decision this project has already taken once. If it is built, it belongs behind an operator-facing route, not in the main navigation — and [STORY-023](#ideas) is the answer for the audience ADR-008 actually describes |

## Done

Closed items, most recent first. Trim to the last two sprints — older history lives in
sprint reviews.

| ID | Item | Sprint |
| --- | --- | --- |
| STORY-056 | A model server is available without installing anything on the host | 4 |
| STORY-054 | The extraction ratchet has been run against a real model at least once | 4 |
| STORY-048 | An ingested edition's derived layer can be built from the running app | 4 |
| STORY-049 | A cold start is empty, and the app says so instead of looking broken | 3 |
| STORY-039 | The graph view fits the window it is drawn in | 3 |
| STORY-040 | Triage only offers comparisons it can actually carry out | 3 |
| STORY-041 | The app has a favicon | 3 |
| STORY-038 | Creating a document through the API is one transaction | 3 |
| STORY-050 | The codebase contains no code the application cannot reach | 3 |
| STORY-053 | Planning documents describe the running app, not its library | 3 |
| STORY-019 | Authentication on the API | — |
| STORY-024 | `POST /query` constrains what a generated query may do | — |
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
