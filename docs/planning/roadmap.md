# Roadmap

*Living document — edit in place. Last reviewed: 2026-08-13*

Sequencing and intent, not commitments with dates. Individual work items live in the
[backlog](../backlog/backlog.md); this is the altitude above that.

## Now

**DI-1 is complete** — 18 of 18 stories, closed on 2026-08-13. One structured CSV in, Neo4j
graph in the middle, CRUD API and a React UI out, exactly as
[SPEC-001](../specs/SPEC-001-di-1-policy-grapher.md) specifies. `docker compose up` ingests
`data/samples/dod_policy_references_08122026.csv` and renders its 23 documents as a navigable graph
at `/`, with the full 438-document corpus listed and searchable at `/documents`. Every
endpoint the spec names is built and covered by tests.

The feasibility question DI-1 existed to answer is answered: the pipeline holds end to end
at sample-corpus scale. What it has not been asked to do is prose parsing or scale — both
of which the next milestone puts to it.

## Next

Closing the gap between DI-1 and the MVP definition of done in the [vision](vision.md):

- **Multi-format ingestion** — DOCX and XLSX alongside CSV and PDF (STORY-035, STORY-036).
  PDF landed in STORY-016; DOCX and XLSX are their own problems, not an extension of it —
  parsing prose documents differs from reading a column of pre-extracted references, and an
  XLSX manifest is closer in shape to the CSV path than to either extraction story.
- **Corpus management** — tables of ingested documents allowing review of extracted text
  and metadata, beyond DI-1's read-only document table.
- **Scale to the MVP bar** — 20 documents, and a graph that stays explorable at the render
  cap (300 nodes by default, configurable). The stored graph will be several times that.
- **Search by document name or ID** as a first-class capability rather than client-side
  table filtering.

## Later

The Policy Concierge capabilities that DI-1's graph schema doesn't yet reach. DI-1 models a
document and one relationship type (`REFERENCES`); the program intent needs considerably more:

- **Policy point extraction** — the unit of interest becomes the individual policy, not the
  document that contains it.
- **Richer metadata and relationships** — which entities a policy applies to, who is
  responsible for enforcing it. Both imply new node labels and relationship types.
- **Lineage views** — showing a policy's ancestry and descendants, not just direct neighbors.
- **External reference handling beyond a label.** DI-1 settled the immediate question:
  cited documents absent from the corpus carry an `:External` label and no `reference_role`
  ([ADR-002](../specs/adr/ADR-002-external-references-and-corpus-first-graph.md), STORY-026),
  and they are 415 of the graph's 438 nodes. What stays open is what they should *become* —
  they exist only as a name, so they cannot be ingested, browsed, or reasoned about until
  something resolves them to real documents.
- **LLM-constructed queries.** The demo assumes users write Cypher
  ([ADR-001](../specs/adr/ADR-001-demo-assumes-cypher-fluent-users.md)); as development
  matures, queries get constructed via LLM instead. This is what opens the system to the
  non-technical audience the corpus implies. Two things gate it: the graph schema settling
  (a natural-language layer over a schema still in migration is wasted work), and
  authentication landing — arbitrary generated Cypher against an unauthenticated `POST /query`
  is a materially different risk from a human typing at a demo.

## Not in the initial surge

Carried from the [vision](vision.md#explicit-non-goals): RAG, vector embeddings, LLM calls,
auth, multi-stage Docker builds, and pagination are all out of scope while the demo
definition of done is the target.

Every one of these is deferred, not excluded. This section is a statement about *now*, not
about the life of the project — LLM-constructed queries already have a place in
[Later](#later), and the rest can earn one the same way.
