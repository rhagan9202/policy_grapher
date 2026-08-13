# ADR-006: Relational facts live on typed edges, not on document properties

**Status:** Accepted · **Date:** 2026-08-13 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

`reference_role` entered the model as the CSV's `Type` column, carrying four values —
`Root Reference`, `Root Reference (Shared)`, `Sub-Reference`, `Sub-Reference (Shared)` —
stored verbatim on each corpus `Document`.
[SPEC-001](../SPEC-001-di-1-policy-grapher.md) was explicit that DI-1 stores it
uninterpreted and does not derive it from structure. Three things have since come to light,
each independently fatal to keeping it as a document property.

**It cannot be derived, so it cannot be validated or maintained.** Three mechanisms were
tested against the sample corpus and all three fail:

| Hypothesis for `(Shared)` | Counter-evidence |
| --- | --- |
| Cited by many documents | `DoDI 5025.01` has 10 corpus citers and is not `(Shared)`; `DoDD 5144.02` has 6 and is |
| Reachable from more than one `Root*` seed | 15 of 23 documents mismatch |
| Directly cited by two or more seeds | `DoDD 5137.02` qualifies but is unlabelled; `DoDD 5000.01` is labelled but does not qualify |

**It is already stale by construction.** `POST /documents/{slug}/references/{target_slug}`
shipped in sprint 2, so edges can be added and removed at runtime while no `reference_role`
anywhere updates. `DoDD 5000.01` is labelled `Root Reference (Shared)` while six corpus
documents cite it.

**Source documents do not carry it.** Extraction work for STORY-016 examined five DoD
issuance PDFs. They contain an identifier, a subject, an effective date, a reissue line and
a references enclosure. Nothing corresponds to `Type`. It is a classification applied when
that CSV was built, not a fact any document states about itself.

Underneath all three sits a modelling error. `Root` and `Sub` describe where a document sits
*in relation to other documents*. A node property cannot express a statement about a pair,
so the label freezes one reading of the edges and then drifts from them.

The program intent makes this decisive rather than tidy. Policy Concierge exists to capture
how issuances, the policies they set, and the entities, procedures and requirements they
govern relate to one another — `references` (document → document), `sets_policy`
(document → policy), `supersedes` (document → document, or policy → policy),
`has_implementation_responsibility_for` (authority → policy). Every one of those is a
statement about a pair. None can live in a column on one node.

## Options considered

**Keep `reference_role`, leave it null for documents ingested from PDFs.** Smallest change.
Preserves an invariant that is already false, and adds a third meaning to null — currently
"external", now also "corpus document we could not classify". Rejected: it spends complexity
defending a field the evidence says is wrong.

**Keep the field but compute it at query time.** Keeps the API shape and removes the
staleness. Rejected because it enshrines a vocabulary we cannot reproduce: no derivation
reproduces the CSV's four values, so the field would keep its name while changing meaning —
the most confusing possible outcome for anyone comparing old and new data.

**Supply the role at ingest, per document.** Preserves the invariant honestly. Rejected: it
requires hand-classifying every document, which defeats ingesting a folder of them, and it
still stores a relational fact on a node.

**Remove it; relational semantics move onto typed edges.** Chosen.

## Decision

1. **`reference_role` is not a property of a document.** It is removed from the graph, the
   Pydantic models, the API, and both frontend views.

2. **`Root` and `Shared` become query-time derivations over edges**, computed where a caller
   actually needs them rather than stored: a corpus document with no incoming `REFERENCES`
   from within the corpus is a root; in-degree greater than one is shared. These are
   definitions this project adopts, not reconstructions of the CSV's labels — they will
   disagree with `Type`, and that is the point.

3. **The relationship type is the extension point for relational meaning.** `REFERENCES` is
   the first member of a vocabulary, not the whole of it. New types are named as directed
   verb phrases in `SCREAMING_SNAKE_CASE`, read source → target.

4. **The named future types are recorded as direction, not as schema.** `SETS_POLICY`,
   `SUPERSEDES`, and `HAS_IMPLEMENTATION_RESPONSIBILITY_FOR` each require node kinds that do
   not exist — `Policy`, and some `Authority` or entity label. They arrive with STORY-020 and
   STORY-021, each with its own design. This ADR commits to the shape of the answer, not to
   those labels' definitions.

5. **The CSV's `Type` column is not migrated into the graph.** The corpus CSV is committed at
   `data/samples/`, so the classification remains recoverable from source if it is ever
   wanted. Nothing is destroyed that cannot be read back.

## Consequences

**`PUT /documents/{slug}` loses its only mutable field.** That endpoint exists solely to
update `reference_role`; `name` changes are already rejected by design
([ADR-003](ADR-003-slug-identifiers.md): rename means delete and recreate). With the field
gone it can update nothing. Whether it is removed outright or repurposed is STORY-034's to
decide, and it is an API removal either way.

**`DocumentIn` loses a required field,** so `POST /documents` takes a name alone. Ingest
stops writing the property, and `documents.py`'s read, create and update Cypher all change.

**Two frontend surfaces lose a display value:** the document table's "Reference role" column
and the graph explorer's node-detail panel, both of which render
`reference_role ?? 'External reference'` today. External documents still need distinguishing
in the UI — `is_external` already carries that, so the fallback becomes the whole answer
rather than a fallback.

**SPEC-001 needs amending** in its node table, `DocumentIn`/`DocumentOut` models, and the
`PUT` row. [ADR-002](ADR-002-external-references-and-corpus-first-graph.md) is unaffected:
`:External` is a label, not this property, and its corpus-first `/graph` rationale stands.

**What this makes easy:** adding relationship types without touching the node schema, and
asking structural questions — roots, shared documents, orphans — as queries that stay true as
the graph changes.

**What this makes harder:** anything that wanted a document's role as a cheap stored lookup
now costs a traversal. At 438 nodes this is irrelevant; it is worth remembering if the corpus
grows by orders of magnitude.

**What it commits us to:** deriving structural views rather than storing them, and to
designing each new relationship type deliberately rather than accumulating properties on
`Document`.
