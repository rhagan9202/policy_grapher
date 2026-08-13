# ADR-001: The initial demo assumes Cypher-fluent users

**Status:** Accepted · **Date:** 2026-08-12 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

Who the users are was the largest open question in the [vision](../../planning/vision.md) —
unstated in the source material and flagged as an open question on
[EPIC-001](../../backlog/epics/EPIC-001-di-1-end-to-end-feasibility.md).

It mattered because it decides the shape of the query surface.
[SPEC-001](../SPEC-001-di-1-policy-grapher.md) exposes `POST /query`, which takes a raw
Cypher string and returns records. Whether that endpoint is the product or an implementation
detail depends entirely on whether a user can write Cypher.

The pressure against deciding it late: every UI story in DI-1 (STORY-009, STORY-010) implies
an answer whether or not one is written down, and reversing an implicit answer costs more
than making an explicit one.

## Options considered

**Assume Cypher fluency for the demo.** Ships `POST /query` as-is. No query-building UI, no
natural-language layer. Narrows the audience to people who can write graph queries.

**Build a guided query UI for the demo.** Filters, dropdowns, saved queries — a
Bloom-like query surface. Broadens the audience but adds substantial frontend scope to an
increment whose purpose is proving the ingest → graph → render spine works at all.

**Build natural-language query construction now.** Widest audience, but requires LLM calls,
which the README places out of initial scope, and would make DI-1 depend on an unproven
extraction layer before the graph itself is proven.

## Decision

The initial demo assumes users are comfortable writing Cypher. `POST /query` is the query
interface; no query-building or natural-language layer is in DI-1 scope.

As development matures, queries will be constructed via LLM. This is a sequencing decision,
not a permanent exclusion — natural-language querying is an intended capability of Policy
Concierge, deferred until the graph underneath it is proven.

## Consequences

What this makes easy, what it makes hard, and what it commits us to.

**Makes easy.** DI-1's frontend scope stays small — the graph explorer and document table
don't need to double as a query builder. The demo audience is technical, so raw Cypher and
raw record payloads are acceptable output, and no result-formatting layer is needed.

**Makes hard.** The demo won't be usable by the policy analysts who are the eventual
audience, so demo feedback will over-represent technical users. Anyone judging the system on
approachability will judge it unfavorably, and that's expected rather than a defect to fix.

**Commits us to.** Keeping `POST /query` stable enough to become the LLM's target surface —
whatever constructs queries later will emit Cypher against this endpoint, so its contract
outlives the demo's audience assumption.

It also sharpens an existing risk: `POST /query` runs arbitrary Cypher with no auth and open
CORS (see [architecture](../architecture.md#known-weak-points)). A Cypher-fluent human at a
demo is a benign caller; an LLM generating queries is a less predictable one. Authentication
and some form of query constraint become prerequisites before that layer ships, not
afterthoughts.

**Revisit when** LLM query construction starts. That work supersedes this ADR's audience
assumption and should be recorded in a new one.
