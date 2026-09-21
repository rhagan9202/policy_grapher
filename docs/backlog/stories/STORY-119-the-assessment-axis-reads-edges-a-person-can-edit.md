# STORY-119: The assessment axis reads edges a person can edit

**Epic:** — · **Status:** Refining · **Estimate:** S

## User story

As an analyst reading a node's assessment state, I want it to describe what the parser actually
found in that document, so that editing the graph by hand does not silently rewrite the record of
what was read.

## Context

Found by the independent cross-model reviewer during U3's code review (run
`20260918-102329-fe8d40c8`), confirmed against the source, and deferred here by the project owner
rather than fixed in U3.

`_assessment` in `backend/src/policy_grapher/graph.py` decides between *assessed, all resolved* and
*assessed, cites nothing* by counting the document's outgoing `:REFERENCES` edges:

    OPTIONAL MATCH (d)-[:REFERENCES]->(out:Document)
    WITH ..., count(DISTINCT out) AS resolved

Those edges are not parser output. `documents.add_reference` and `documents.remove_reference` —
behind `POST` and `DELETE /documents/{slug}/references/{target_slug}` — let a person add or delete
any of them, and [ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md) makes an asserted
edge a legitimate state rather than corruption.

So two things follow that the axis is not supposed to permit:

- **Delete a parsed edge** and the document reports *assessed, cites nothing* on the next request,
  while the stored parse facts still say a section was located and every entry resolved.
- **Add an edge by hand** to a document whose parse attributed nothing, and it reports *assessed,
  all resolved*.

The axis exists to say what the parser established. Half of it is currently computed from what
somebody has since edited.

## Why it was not fixed in U3

U3's file list covers the graph read path. The fix is a write-path change: ingest has to persist a
positive attributed-reference signal, which is a new property on `:Document` and a new line in
`MERGE_DOCUMENT`. That is U1's territory —
[KTD1](../../plans/2026-09-17-0801-feat-dependency-map-home-plan.md) already states the governing
principle, that the reference-resolution outcome is persisted *because no query can recompute it*,
and U1 stored only the negative half (`references_unattributed`) while leaving the positive half to
be inferred from the graph. This story closes that gap.

Note that [AGENTS.md](../../../AGENTS.md) rule 2 says filing a story is not a substitute for fixing
a defect. This was deferred as an explicit owner decision, with the trade recorded here: the fix
needs a schema addition and a backfill answer, and U3 ships a correct ladder either way.

## The decision this needs

**What happens to documents already in the graph that carry no attributed count?**

- **Treat absent as unknown** and report `not_assessed` until the document is re-ingested. Honest,
  and consistent with how `references_section_found` already reads absence — but it demotes
  documents whose assessment is correct today.
- **Fall back to the edge count when the property is absent.** No visible change for existing data,
  at the cost of keeping the defect alive on exactly the documents nobody has re-ingested.
- **Backfill from a re-ingest sweep.** Cleanest end state, and the most work; it also interacts with
  [ADR-042](../../specs/adr/ADR-042-an-ingest-that-would-rewrite-nothing-rewrites-nothing.md), since
  an unchanged re-ingest is now a no-op and would not write the new property at all.

That last interaction is the one to settle first: under ADR-042 a no-op re-ingest rewrites nothing,
so a backfill cannot ride on re-ingesting unchanged files.

## Acceptance criteria

- Ingest persists a parser-owned count of the references it attributed, alongside the unattributed
  entries it already stores, and self-references are accounted for explicitly one way or the other.
- `_assessment` decides *all resolved* versus *cites nothing* from that stored signal, not from
  `:REFERENCES` edges.
- Adding or deleting a reference through the API changes the drawn edges and leaves the node's
  `assessment_state` unchanged — asserted by a test, since that is the whole defect.
- The absent-property case has a stated, tested behaviour per the decision above.
