# ADR-004: POST /query stays unrestricted in DI-1

**Status:** Accepted · **Date:** 2026-08-12 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-001](ADR-001-demo-assumes-cypher-fluent-users.md) made `POST /query` the demo's entire
query interface: the audience writes Cypher, so the passthrough endpoint is the product
rather than a debugging affordance.

That raised the question of what limits it should carry in DI-1. As specified, it accepts an
arbitrary Cypher string and executes it. Combined with two other DI-1 decisions — no
authentication, and CORS open to all origins — the endpoint is reachable by any page in any
browser on a machine that can route to the backend, and `MATCH (n) DETACH DELETE n` is a
valid body.

The counterweight: DI-1 runs locally, on a demo corpus that is regenerated from a CSV in
seconds, and the increment's purpose is proving the ingest → graph → render spine. Limits
are scope that doesn't serve that goal.

## Options considered

**Read-only transaction, timeout, and row cap.** Run queries in a Neo4j read transaction so
writes are rejected at the driver level, with a query timeout and a maximum row count.
Modest work. Would also mean the exploratory endpoint can't be used to fix data.

**Row cap only.** Prevents runaway payloads and a hung browser tab, while still permitting
deletes. Half a guardrail.

**No limits.** Ship the endpoint as SPEC-001 describes it.

## Decision

`POST /query` executes arbitrary Cypher in DI-1 with no read-only enforcement, no timeout,
and no row cap.

This is a **deliberate acceptance of a known risk**, not an oversight, and it is bounded by
the conditions that make it defensible:

- The stack is local-only. It must not be exposed on a shared network or a hosted
  environment in this form.
- The data is disposable — `POST /reset` plus a re-ingest rebuilds the graph from the CSV.
- The audience is Cypher-fluent and trusted ([ADR-001](ADR-001-demo-assumes-cypher-fluent-users.md)).

If any of those three stops holding, this decision needs revisiting before the change ships,
not after.

## Consequences

What this makes easy, what it makes hard, and what it commits us to.

**Makes easy.** The endpoint is maximally useful for exploration — a demo viewer can inspect,
correct, and experiment without a second interface. No transaction-mode plumbing, no
serialization limits to tune, no scope added to an increment that needs to prove something
else. A destructive accident costs a reset and an ingest.

**Makes hard.** The endpoint can't move outward as-is. Any step toward a shared environment —
a hosted demo, a colleague running it on a reachable host, a CI environment with real data —
requires this work first, and it will land under time pressure rather than at leisure.

**Commits us to.** Two prerequisites before LLM-constructed queries ship, both already in
the backlog: authentication (**STORY-019**) and query constraints (**STORY-024**). A
Cypher-fluent human typing at a demo is a benign caller and a generated query is not, so the
audience change described in [ADR-001](ADR-001-demo-assumes-cypher-fluent-users.md) is the
event that forces this one. The safest reading: **this ADR expires when ADR-001 does.**

**Recorded so it isn't rediscovered.** This is listed as a known weak point in
[architecture.md](../architecture.md#known-weak-points). It should stay there until it's
fixed, so that nobody has to work out from first principles why an unauthenticated Cypher
passthrough was ever acceptable.
