# ADR-009: `POST /query` is read-only and bounded

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

**Supersedes [ADR-004](ADR-004-unrestricted-cypher-in-di-1.md).** ADR-004 accepted unrestricted
Cypher through `POST /query` as a deliberate, bounded risk, and named the three conditions that
bounded it: the stack stays local-only, the data is disposable, and the audience is
Cypher-fluent and trusted. This ADR changes the decision because DI-2 breaks all three at once.

## Context

DI-2 targets a hosted deployment ([design](../../superpowers/specs/2026-08-20-di-2-design.md)),
which is exactly the event ADR-004 named as its own revisit trigger: "this ADR expires when
ADR-001 does." Once the app is reachable outside a single local machine, none of ADR-004's
three conditions holds:

- **Local-only** stops holding the moment the backend is reachable from a shared network or a
  hosted environment — the thing ADR-004 explicitly said must not happen "in this form."
- **Disposable data** stops being the whole story once DI-2 ingests real corpus documents
  (US Code titles, OMB circulars, DoD issuances) rather than only a regenerable demo CSV.
- **Trusted, Cypher-fluent audience** stops holding once queries can originate from something
  other than a human typing at a demo — including, eventually, an LLM constructing a query
  from a document the corpus itself supplied. ADR-004 named this precisely: "a Cypher-fluent
  human typing at a demo is a benign caller and a generated query is not."

`POST /query` today accepts arbitrary Cypher, routes it as a WRITE, and enforces no timeout and
no row cap. Left as-is against a hosted deployment, `MATCH (n) DETACH DELETE n` is a valid,
unauthenticated body with no bound on execution time or response size. This is Phase 0 of the
DI-2 security gate: authentication (STORY-019) lands separately and later. This task closes
STORY-024 — the query-constraints half of the two prerequisites ADR-004 itself named.

## Options considered

**Read-only transaction, timeout, and row cap.** Run queries in a Neo4j read transaction so
writes are rejected at the driver level, bound execution with a transaction timeout, and cap
the number of rows returned, reporting truncation rather than silently dropping rows. This is
the option ADR-004 already scoped and rejected only for being out of scope in DI-1. Modest,
well-understood work; the endpoint can no longer be used to fix data in place.

**Row cap only.** Prevents runaway payloads and a hung browser tab, while still permitting
deletes. Half a guardrail — leaves the sharp edge ADR-004 named untouched.

**No limits, defer to authentication alone.** Wait for STORY-019 and rely on auth as the only
gate. Rejected: authentication controls *who* can call the endpoint, not *what* the endpoint
lets them do once they're in, and ADR-004 named query constraints as a separate prerequisite
for exactly this reason.

## Decision

`POST /query` is read-only, time-bounded, and row-capped:

1. **Read routing.** Queries execute via `RoutingControl.READ`. Neo4j rejects a write attempted
   in a read transaction at the driver level — the enforcement is the database's, not a regex
   over the query text.
2. **Transaction timeout.** Each query carries a timeout (`query_timeout_seconds`, default
   `10.0`), so a runaway or pathological query cannot hang a request indefinitely.
3. **Deterministic row cap.** Results are capped at `query_row_cap` rows (default `1000`).
   Truncation is always reported in the response (`truncated: bool`, alongside
   `returned_rows`), never silent — silent truncation is the failure mode this project treats
   as worse than an obviously incomplete result, matching the contract `GET /graph` already
   uses (`total_nodes` / `returned_nodes` / `truncated`).

Mutation does not disappear — it moves. `POST /query` was, until now, the only way to create,
edit, or delete graph data outside the ingest pipeline and the existing typed document/reference
routes. Ad hoc mutation through this endpoint moves to authenticated admin routes once
STORY-019 lands; it is not simply removed.

## Consequences

**Makes easy.** The endpoint is safe to expose once authentication arrives — a compromised or
malicious query can inspect but not corrupt the graph, and cannot hang a worker indefinitely.
It also brings `/query` in line with `/graph`'s existing truncation contract, so a frontend
consumer handles both the same way.

**Makes hard.** The exploratory, fix-data-through-the-console workflow ADR-004 explicitly
valued is gone. A demo viewer who wants to correct data now needs a mutation path with an
identity behind it, not a Cypher box. This is deliberate: ADR-004 accepted that cost the moment
its own three conditions stopped holding, and named the tradeoff explicitly.

**Commits us to.** A future authenticated mutation route needs its own design — this ADR does
not specify it, only asserts that it is where mutation goes. `query_row_cap` and
`query_timeout_seconds` are configuration, not architecture, and may need retuning once real
corpus queries (not the demo CSV) show what a legitimate result set looks like.

**Recorded so it isn't rediscovered.** ADR-004's known-weak-point entry in
[architecture.md](../architecture.md#known-weak-points) is resolved by this ADR for the
query-constraints half; authentication (STORY-019) remains outstanding.
