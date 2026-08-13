# EPIC-001: DI-1 — end-to-end feasibility

**Status:** Not started · **Target:** DI-1

## Goal

Prove the Policy Grapher pipeline works end to end on a single structured CSV: file on
disk → Neo4j graph → CRUD API → force-directed React UI, all running under Docker Compose.

## Why now

Every later capability in the [vision](../../planning/vision.md) — multi-format ingestion,
policy point extraction, entity and enforcement metadata — assumes this spine exists. Until
one document set makes it all the way from disk to a rendered graph, the architecture is
unvalidated and the harder extraction work has nothing to build on.

## Scope

In scope:
- CSV ingestion with the exact three-column format in [SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md)
- `Document` nodes and `REFERENCES` relationships, merged idempotently
- Full document CRUD, a `/graph` endpoint, and a raw Cypher `/query` endpoint
- Two UI routes: graph explorer and document table
- Three-service Docker Compose setup

Out of scope:
- PDF, DOCX, XLSX ingestion (deferred — see STORY-016)
- Authentication and authorization
- RAG, LLM calls, vector embeddings — out of scope for this increment
- Production multi-stage Docker builds
- Corpus management beyond the read-only document table
- Pagination

## Stories

| ID | Item | Status |
| --- | --- | --- |
| STORY-001 | Stack comes up with one command | Ready |
| STORY-002 | Neo4j connection and unique constraints | Ready |
| STORY-025 | Stable URL-safe slugs | Ready |
| STORY-003 | Idempotent CSV ingestion | Ready |
| STORY-026 | External documents distinguishable | Ready |
| STORY-004 | Malformed CSV rejected cleanly | Ready |
| STORY-005 | List documents, read one with both directions | Ready |
| STORY-006 | Create, update, delete documents | Ready |
| STORY-027 | Add and remove references | Ready |
| STORY-007 | Corpus-first graph endpoint | Ready |
| STORY-028 | Reset the graph | Ready |
| STORY-008 | Raw Cypher query endpoint | Ready |
| STORY-009 | Graph explorer with expansion | Ready |
| STORY-010 | Searchable document table | Ready |
| STORY-011 | Typed API client | Ready |
| STORY-029 | Auto-ingest on empty graph | Ready |
| STORY-030 | Integration tests on a disposable Neo4j | Ready |
| STORY-012 | Sample DoD corpus loads end to end | Ready |

Six stories (025–030) came out of the 2026-08-12 gap review — they close holes the original
spec left rather than adding scope. STORY-025 and STORY-026 are prerequisites for most of
the endpoints above.

Detail lives in [backlog.md](../backlog.md) — none of these has needed its own file yet.

## Open questions

A gap review on 2026-08-12 closed most of these. Resolved entries are struck through rather
than deleted, so the reasoning stays findable.

- ~~**Who are the users?**~~ **Resolved:** the demo assumes Cypher-fluent users;
  LLM-constructed queries come later — [ADR-001](../../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md).
- ~~**How should out-of-corpus references be modeled?**~~ **Resolved:** `:External` label,
  corpus-first `/graph` — [ADR-002](../../specs/adr/ADR-002-external-references-and-corpus-first-graph.md).
  Now STORY-026.
- ~~**What is the acceptance bar for "renders"?"**~~ **Partly resolved:** the default view is
  the 23 corpus documents, which is legible by construction. Still unstated is what good
  looks like with `include_external=true` at 438 nodes — see STORY-015.
- **Is there a CI target?** Still open, and now sharper: STORY-030 puts integration tests on
  `testcontainers`, so **any CI needs Docker-in-Docker or an equivalent**. Worth answering
  before the test suite is written, not after.
- ~~**Is the MVP's 300-node ceiling still right?**~~ **Resolved 2026-08-12:** it is a
  configurable **render cap** (`GRAPH_RENDER_CAP`, default 300), bounding what's drawn at
  once rather than what's stored. Restated in the [vision](../../planning/vision.md) and
  specified with a deterministic truncation rule in
  [SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md#render-cap-gap-review). Now STORY-015.
- **How should a document be renamed?** [ADR-003](../../specs/adr/ADR-003-slug-identifiers.md)
  says delete and recreate. Fine for a fixed demo corpus; an obvious gap once corpus
  management arrives.
