# ADR-002: External references get their own label, and /graph is corpus-first

**Status:** Accepted · **Date:** 2026-08-12 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

Measuring the sample corpus against the spec turned up a mismatch nobody had priced in.
`data/dod_policy_references_08122026.csv` holds 23 documents, but they cite 436 distinct
names, of which **415 are not in the corpus** — public laws, MIL-STDs, CFR titles, DHS and
Joint Chiefs memoranda. Under SPEC-001's `MERGE`-on-name ingestion, every one becomes a
`Document` node.

So one file produces **438 nodes**, against an MVP visualization ceiling of 300. The demo
would exceed its own stated limit on first run, and 95% of what it rendered would be nodes
with no `type` — documents nothing in the corpus describes.

Two questions fell out, and they interact: what belongs in the database, and what belongs
on screen.

## Options considered

**Drop external references at ingest.** 23 nodes, ~21 edges. Comfortably under the ceiling
and trivial to build — but it discards 95% of the reference data, which is the actual
subject of the project, and the demo graph becomes too sparse to be interesting.

**Ingest everything and render everything.** Faithful, and it tests the renderer at real
scale. Risks an unreadable hairball as the first thing anyone sees, and breaks the 300-node
bar the MVP commits to.

**Curate a smaller CSV.** Keeps every stated limit intact, at the cost of demoing on data
shaped to fit the demo. The 438-node problem returns unchanged the first time real data
arrives.

**Ingest everything, filter the view.** Store all 438; default the graph view to the corpus
and let external nodes in on demand.

For labeling the external nodes specifically: a distinct `:External` label, a boolean
`in_corpus` property, a sentinel `type` value, or leaving `type` null as the spec implied.

## Decision

**Ingest all 438 nodes.** The graph holds the complete reference structure.

**External documents carry an additional `:External` label** alongside `:Document`, and have
no `reference_role`. `MATCH (d:Document)` returns everything; `MATCH (d:Document) WHERE NOT
d:External` returns the 23 corpus documents.

**`GET /graph` is corpus-first.** It returns the 23 corpus documents and the edges among
them by default, with `?include_external=true` for the whole graph and `?expand={slug}` to
pull in one document's external neighbors.

Relatedly, **`type` is renamed `reference_role`** and stored verbatim. Its four values
(`Root Reference`, `Sub-Reference`, and their `(Shared)` variants) describe a document's
position in the reference graph, not what kind of document it is — calling it `type` invited
exactly the wrong query.

## Consequences

What this makes easy, what it makes hard, and what it commits us to.

**Makes easy.** The default view is legible and under the ceiling without discarding data.
Corpus-versus-external is a label check rather than a property filter, so it's fast, visible
in the Neo4j browser, and hard to forget — a query that omits the filter returns everything
rather than silently including externals, which is the failure mode a boolean property has.
The UI can style external nodes differently with no extra lookup.

**Makes hard.** Two labels and a nullable `reference_role` mean every consumer handles the
distinction. `GET /graph`'s parameters are now part of the contract, and the expand
interaction is real frontend work the original spec didn't have.

**Commits us to.** A graph whose node count is driven by reference breadth, not corpus size.
Twenty documents at this citation density is closer to 400 nodes than 300 — **the MVP's
300-node ceiling is probably already wrong**, and the honest reading is that it constrains
what's *rendered at once*, not what's stored. Worth restating in the MVP definition of done
before it's measured against.

**Left undecided.** Whether near-duplicate external names denote the same document. Ingest
flags them and moves on; entity resolution is deliberately not DI-1's problem.
