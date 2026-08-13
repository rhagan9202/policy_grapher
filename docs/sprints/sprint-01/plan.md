# Sprint 1 — Plan

**Dates:** TBD → TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

**TODO:** Dates, capacity, estimates, and owners are unset — this plan was drafted from
[SPEC-001](../../specs/SPEC-001-di-1-policy-grapher.md) before any planning session
happened. Confirm the commitment below is real before treating it as one, and fill in the
blanks at planning. If the scope changes, rewrite this file then freeze it.

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

Ingest the sample DoD corpus and see it rendered as a navigable graph — the DI-1 spine
working end to end on one machine.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-001 | A developer can bring the full stack up with one command | — | — |
| STORY-002 | Backend connects to Neo4j and enforces unique constraints on `slug` and `name` | — | — |
| STORY-025 | Every document gets a stable, URL-safe slug that survives re-ingest | — | — |
| STORY-003 | A CSV of documents and references becomes a graph, and re-ingesting it changes nothing | — | — |
| STORY-026 | External documents are distinguishable from corpus documents in the graph | — | — |
| STORY-007 | The UI can fetch a legible graph in one call | — | — |
| STORY-011 | The frontend talks to the backend through one typed API client | — | — |
| STORY-009 | A user can see the corpus as a force-directed graph, click a node, and expand its external references | — | — |
| STORY-029 | The stack comes up with the sample corpus already loaded | — | — |
| STORY-012 | The sample DoD corpus loads and renders end to end | — | — |

**Total committed:** Unestimated — see [the estimation TODO](../../backlog/README.md#estimation).

These ten are the thinnest path to the sprint goal. The 2026-08-12 gap review added three of
them: STORY-025 (slugs) and STORY-026 (`:External`) are prerequisites rather than extras —
without slugs no document endpoint has a working URL, and without the label the default graph
view can't filter to the corpus. STORY-029 is what makes the goal literally true, since
`compose up` otherwise renders an empty canvas.

Document CRUD (STORY-005, STORY-006), reference editing (STORY-027), reset (STORY-028), the
Cypher endpoint (STORY-008), and the document table (STORY-010) are all in DI-1 scope but
none is needed to prove the spine, so they sit below the line. STORY-030 (testcontainers) is
deliberately not committed — see risks.

## Stretch

Picked up only if committed work finishes early:

- STORY-005 — list documents and read one with its references
- STORY-010 — searchable document table
- STORY-004 — reject malformed CSVs cleanly

## Known risks

- **Python ≥ 3.14 is a hard floor.** Base image availability and library support for a
  version this recent are worth checking on day one, not day four. This is the single most
  likely source of a lost day.
- **Nothing exists yet.** There is no scaffolding, no manifests, no compose file — the
  sprint starts from an empty repo, so setup cost lands entirely inside it.
- **`neo4j:latest` is unpinned**, so two developers can end up on different database
  versions. Cheap to fix now (STORY-018), annoying to diagnose later.
- **Force-graph rendering is unproven at this corpus size.** 23 documents plus their
  out-of-corpus reference targets is more nodes than the row count suggests — the CSV's
  reference lists run up to 18 entries each.
- **Testing strategy is committed but the story isn't.** STORY-030 puts integration tests on
  disposable Neo4j containers, which makes Docker a hard prerequisite for running tests at
  all. If it slips out of this sprint, the Definition of Done ("tests written and passing")
  can't be met for anything above — so either pull it in or accept that sprint 1 closes with
  the gate unmet. Decide at planning rather than at review.
- **Slug collision handling will be under-tested.** The sample corpus may not collide at all,
  so STORY-025's collision branch needs a deliberate test rather than incidental coverage.
  It's the kind of thing that works for a year and then doesn't.
