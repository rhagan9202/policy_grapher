# ADR-007: Sources describe documents, and `:External` is a view of that

**Status:** Accepted · **Date:** 2026-08-13 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

**Amends [ADR-002](ADR-002-external-references-and-corpus-first-graph.md).** ADR-002 stands:
the graph holds all 438 nodes, `:External` distinguishes cited-only documents, and
`GET /graph` is corpus-first. This ADR changes what maintains that label and, as a
consequence, when a document loses it.

## Context

[ADR-002](ADR-002-external-references-and-corpus-first-graph.md) coined `:External` for
"documents nothing in the corpus describes" — the 415 names the sample corpus cites but does
not contain. At the time, two properties always coincided:

1. the document is not a row in the manifest, and
2. we hold no first-hand record of it — we know only that something cited it.

**PDF ingestion (STORY-016) split those apart.** A document ingested from its own PDF is
described first-hand, in full, while very possibly not appearing as a row in the corpus CSV.
The two writers of the label now disagree, and the manifest wins by running last:
`MERGE_EXTERNAL` sets `:External` on any name the manifest cites, including one a PDF just
described. That document then vanishes from the default `GET /graph` view, which selects
`WHERE NOT d:External`, and reappears only as an expandable citation target.

A second, older tension sits underneath. `MERGE` never deletes, and
[SPEC-001](../SPEC-001-di-1-policy-grapher.md) says so plainly — *"Ingest is additive… never
deletes. To make the graph match a changed file, reset first."* Yet a manifest that drops a
document demotes it, which is the one place ingest is subtractive. That was coherent while
the manifest was the label's only owner. With two owners it is a race.

There is also a precedent worth naming.
[ADR-006](ADR-006-relational-facts-live-on-typed-edges.md) removed `reference_role` because a
stored label describing a document's standing *relative to other documents* went stale the
moment edges became editable. `:External` is the same shape one level up: a stored label
describing a document's standing *relative to a corpus*, going stale the moment a second
ingest path can describe the same node. The lesson transfers.

## Options considered

**A boolean marker on the node** — e.g. `from_document`, set by PDF ingest, checked by the
manifest's external pass. Two lines of Cypher, preserves today's behaviour exactly, and needs
no migration. Rejected not because it fails, but because it answers only this defect: it
records *that* something described a document, never *what*, so corpus management (STORY-017)
would have to replace it almost immediately.

**A provenance list on the node** — `sources: ["manifest:corpus.csv", "document:500001p.pdf"]`,
with `:External` derived from emptiness. Answers the provenance question, but stores a
collection of relationships as a node property, which is precisely the shape ADR-006 argued
against. It is the awkward middle: the cost of modelling provenance without the benefits.

**Source nodes and edges.** Chosen.

## Decision

1. **An ingest is a node.** `(:Source {id, kind, filename})` where `kind` is `manifest` or
   `document` and `id` is `"<kind>:<filename>"`. Ingesting the same file twice `MERGE`s the
   same node.

2. **Describing is an edge.** `(:Source)-[:DESCRIBES]->(:Document)`, created for each document
   an ingest describes first-hand: every corpus row of a manifest, and the single subject of a
   PDF. A cited-only name gets no `DESCRIBES` edge — that is exactly what makes it external.
   The type is a directed verb phrase in `SCREAMING_SNAKE_CASE`, following ADR-006.

3. **`:External` is a materialised view, maintained from one rule.** A `Document` with no
   incoming `DESCRIBES` carries `:External`; one with any incoming `DESCRIBES` does not. Every
   ingest path recomputes the label for the nodes it touched, using the same statement. The
   label is kept — ADR-002 chose it for query ergonomics and `WHERE NOT d:External` remains
   cheap — but no path sets it according to its own opinion any more.

4. **A document created through the API is described by the API.** `POST /documents` records
   `(:Source {id: "api", kind: "api"})` as describing what it creates. Without this the rule
   has a hole: after ADR-006 that endpoint supplies nothing but a name, so a hand-created
   document has no provenance and would evaluate as external — invisible in the default graph
   view moments after a user created it, and a permanent false positive for any check that the
   label matches provenance. Treating the user's assertion as a source is the honest reading:
   somebody stated first-hand that this document exists. The three kinds are therefore
   `manifest`, `document` and `api`.

5. **Ingest becomes uniformly additive.** A document dropped from a later manifest keeps its
   `DESCRIBES` edge from the earlier one and therefore stays non-external. This **changes
   tested behaviour**: `test_a_document_transitions_correctly_in_either_direction` currently
   asserts that such a document is demoted. That demotion was the sole subtractive act in an
   otherwise additive pipeline, and it contradicted SPEC-001's own statement. Promotion in the
   other direction — a cited-only document becoming described — is unchanged and still tested.
   `POST /reset` remains the way to make the graph match a changed file.

## Consequences

**The `api` source is coarse on purpose.** One node for every hand-created document, not one
per creation, because DI-1 has no users to attribute to and inventing per-request sources would
be provenance theatre. When authentication arrives (STORY-019) it becomes the obvious place to
record who, and that is a new decision rather than a change to this one.

**Provenance becomes answerable.** "Where did this document come from?" is a one-hop query,
and STORY-017's review screen has something real to show. A document described by both a
manifest and its own PDF shows both.

**Reported counts change, and the change is visible.** `POST /reset` reports literal totals
from `MATCH (n) DETACH DELETE n`, so after one CSV ingest it will report **439 nodes and 695
relationships** rather than 438 and 672 — the extra being one `:Source` and its 23 `DESCRIBES`
edges. `POST /ingest`'s `nodes_created` and `relationships_created` must continue to count
only `Document` nodes and `REFERENCES` edges; source bookkeeping is not what the caller asked
about, and letting it leak into those counters would make them meaningless.

**Existing graphs need a reset.** A graph built before this change has no `:Source` nodes, so
every document would evaluate as external. Data is local and disposable
([ADR-004](ADR-004-unrestricted-cypher-in-di-1.md)) and reset-then-reingest is the documented
path, so no migration script is written — but the next ingest after upgrading must be a reset.

**A third label to keep honest.** `:External` is now derived but still stored, so it can still
drift if a future write path forgets to recompute it. That risk is smaller than today's — one
rule, applied in one place — but it is not zero. The check that it has not drifted is a single
query, and belongs in the test suite rather than in a reviewer's memory.

**An `:External` document can still carry an outgoing edge.**
`POST /documents/{slug}/references/{target_slug}` gives any document a `REFERENCES` edge and
never touches its label — that endpoint asserts a relationship, not a description. A document
with no incoming `DESCRIBES` but an outgoing `REFERENCES` is therefore a legitimate state
under Decision 3, not a contradiction of it: the label answers only "did any source describe
this document," and a user asserting an edge from it is not a source describing it.

**What this makes easy:** attributing any document to what described it, and adding a second
kind of source (DOCX, XLSX) without touching the label logic. **What it makes harder:** nothing
in the query path — `WHERE NOT d:External` is unchanged — but every ingest now writes two extra
statements, and a graph of ingests accumulates source nodes that nothing prunes.

**Direction, not schema.** `DESCRIBES` is the second member of the typed vocabulary ADR-006
opened, after `REFERENCES`. `SUPERSEDES` and the policy-level types remain unbuilt.
