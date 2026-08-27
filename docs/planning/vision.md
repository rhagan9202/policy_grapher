# Vision

*Living document — edit in place. Last reviewed: 2026-08-13*

## The problem

Policy corpora are dense webs of cross-references. A single DoD directive cites a dozen
other directives, instructions, manuals, public laws, and standards — and those cite
further documents in turn. The corpus in `data/samples/dod_policy_references_08122026.csv` shows
the shape: 23 documents, each carrying up to 18 outbound references, including references
to documents outside the corpus entirely.

That structure exists only implicitly, buried in prose. Answering "what else is affected
if this instruction changes?" or "what is the lineage of this requirement?" means reading
documents by hand and holding the graph in your head.

## Who this is for

The audience changes as the system matures, and the demo's audience is deliberately not the
eventual one.

**The initial demo assumes users are comfortable writing Cypher.** `POST /query` is the
query interface; there is no query-building or natural-language layer in DI-1. Recorded in
[ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md).

**As development matures, queries will be constructed via LLM**, opening the system to users
who don't write graph queries — the policy analysts and compliance staff the corpus implies.
See [Later](roadmap.md#later) for where that sits in the sequence.

> **Assumption:** Users are internal to the organization holding the corpus, with no
> authentication needed for the demo. Inferred from DI-1 explicitly deferring auth and
> allowing all CORS origins. Confirm before this hardens into a design constraint.

Still open: whether agents are first-class consumers alongside humans. The README names
"users/agents" as API consumers, but nothing specifies what an agent needs that a human doesn't.

## What we're building

Policy Grapher is the feasibility demonstration and MVP for a larger program, **Policy
Concierge** — a knowledge and policy management system.

The full program intent, per the repo README:

- Ingest policy documents and guidelines; extract policy points and metadata — which
  entities a policy applies to, who enforces it, what it references
- Construct a Neo4j knowledge graph capturing the relationships between documents and
  policies
- Expose an API for users and agents to query that graph with Cypher
- Provide a lightweight UI for visual exploration, comparable to Neo4j Bloom
- Let users search for a document or policy and see it alongside its related documents,
  lineage, and metadata

This repo carries that from nothing to a working end-to-end slice. See the
[roadmap](roadmap.md) for the order.

## What success looks like

The MVP definition of done, from the README:

- Handles a corpus of 20 documents
- Ingests documents from the file system
- Processes PDF, DOCX, XLSX, and CSV file types. **CSV, PDF and XLSX are done; DOCX is blocked
  and has been since sprint 5** — not deprioritised, unstartable. There is no `.docx` anywhere in
  this repository to design extraction against, and the blocker is a missing input rather than a
  missing intention: PDF's extraction rules were built against seven real DoD issuances and are
  held by a ratchet scoring them against a corpus CSV describing those documents
  ([ADR-013](../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)). Rules fitted to a
  DOCX we invented would encode our own guess at DoD's conventions, and that same ratchet could
  not tell us they were wrong. **What unblocks it is one genuine DoD issuance in DOCX in
  `data/samples`.** XLSX sits in this sentence and was never blocked, because a manifest is a
  format this project defines rather than one it has to discover (STORY-036).
- Spins up and runs on Docker containers, on a **current, pinned** Neo4j image. The source
  requirement said "the latest Neo4j container"; taken literally that makes the database
  version depend on when the image was last pulled, so two machines can differ. STORY-018
  pins an explicit current version instead — `2025.10` today — which meets the intent
  (a modern Neo4j, not a legacy one) without the irreproducibility. Bumping the pin is
  routine work, not a deviation from this bar.
- Visualizes and explores a graph up to a **configurable render cap, defaulting to 300
  nodes**. This bounds what is drawn at once, not what is stored — the graph itself is
  expected to be larger, since node count tracks citation breadth rather than corpus size
  (23 corpus documents already yield 438 nodes)
- Corpus management via tables of ingested documents, allowing review of text and metadata
- API calls return successful queries with correct payloads
- Users can search by document name or ID

The nearer bar is DI-1, scoped in [SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md):
the same pipeline end to end, but CSV-only and without the corpus management surface.

For the initial demo, "a user can query the graph" is met by a Cypher-fluent user calling
`POST /query` directly. Approachability to non-technical users is explicitly not part of the
demo bar — see [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md).

## Explicit non-goals

Out of scope for the **initial surge** — the demo definition of done. Naming them keeps the
demo focused; none is a judgment about the life of the project.

- **RAG functionality.** DI-1 builds its graph from structural references only.
- **Vector embeddings and vector stores.** No semantic search layer in the demo.
- **LLM calls.** Natural-language query construction arrives as development matures — see
  [ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md) and
  [Later](roadmap.md#later).
- **Authentication and authorization** (DI-1 scope decision; the MVP bar is silent on it).
  Becomes a prerequisite before LLM-constructed queries ship.
- **Production-grade Docker builds** — DI-1 uses single-stage images.
- **Pagination** — the render cap bounds response size instead, so the corpus stays small
  enough (≤20 documents) that paging isn't needed.

These are sequencing decisions, deferred while the initial surge proves the ingest → graph →
render spine. Don't quote any of them as a permanent restriction. When one is revisited,
record the decision in an [ADR](../specs/adr/) rather than editing this list into a promise.

## Constraints

**Backend:** Python ≥ 3.14, FastAPI, Pydantic v2, the official `neo4j` driver, `uv` for
dependency management, pytest and httpx for tests.

**Frontend:** React, Vite, TypeScript, vitest, `react-force-graph` (2D), `react-router-dom`.

**Infrastructure:** Docker Compose, a current Neo4j image pinned to an explicit version
(`2025.10` today) rather than `latest` — see STORY-018 and the note under
[What success looks like](#what-success-looks-like).

Python ≥ 3.14 is a hard floor worth noting — it constrains which base images and which
library versions are available.
