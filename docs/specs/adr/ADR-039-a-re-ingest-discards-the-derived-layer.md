# ADR-039: A re-ingest discards the derived layer it invalidates

**Status:** Accepted, amended by [ADR-042](ADR-042-an-ingest-that-would-rewrite-nothing-rewrites-nothing.md) · **Date:** 2026-09-09 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

Taken while repairing a defect found on 2026-09-08, driving the containerised stack against
a graph that had been rebuilt with a real extractor.

## Context

`_write_document` has replaced an edition's chunks since PDF ingest was written — `drop_chunks`
then `write_chunks`, in one transaction, so that a re-scan or a chunker improvement does not
leave the previous run's chunks orphaned beside the new ones. That much was deliberate and
commented.

`drop_chunks` is a `DETACH DELETE`. It removes each chunk **and every relationship touching
it**, including the `:ANCHORED_IN` edges by which obligations cite the passage they were read
from. An obligation hangs off its edition by `:MANDATES`, not off the chunk, so it survives the
drop — unanchored.

Nothing failed. `POST /ingest` answered 200, the obligation count was unchanged, and the damage
was visible only to a screen that asked for the obligations themselves:

> 62 obligations. Showing the first 0.

`COUNT_OBLIGATIONS` matches `(:DocumentVersion)-[:MANDATES]->(:Obligation)` and saw 62.
`LIST_OBLIGATIONS` additionally binds each obligation's anchoring chunk through
`primary_anchor`, whose `CALL` subquery is an inner join, and saw none. Both queries were
correct about what they asked. The graph beneath them was not.

The counts stayed wrong in the reader's favour, which is the dangerous direction: Triage went
on reporting `from_obligations: 83, to_obligations: 62` and ranking 133 changes over clauses no
screen could display, and a Review proposal needs a citation from each side.

Two things made this worse than a stale number. Extraction with a real model costs roughly a
minute and a half per chunk ([ADR-023](ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)),
so the orphaned obligations represented about an hour of work. And re-ingesting is *routine* —
ADR-007 makes ingest additive precisely so that running it again is safe.

## Options considered

**Re-anchor the surviving obligations.** On an unchanged re-ingest the new chunk ids are
identical — they hash `(version_id, section_path, ordinal)` — so the edges could in principle be
rebuilt. Rejected. It is only sound when the chunker's output has not changed, and the case the
drop exists for is precisely a chunker that *has* changed; the machinery would then be
reattaching extraction to text it was not read from, which is worse than losing it, because
nothing on screen would say the citation no longer points where the model looked.

**Refuse to re-ingest an edition holding obligations.** Honest, and it protects the expensive
artefact. Rejected: it makes re-ingest conditional on derived state, so the safe, additive
operation ADR-007 describes would start failing for reasons about a layer above it — and the
way out would be `POST /reset`, which destroys far more.

**Drop the derived layer with the chunks it is built on.** Chosen.

## Decision

`_write_document` drops the derived layer before it drops the chunks, in the order
`links/rebuild.py` already established for the same hazard — changes, then obligations, then
chunks — and then clears the edition's build record.

Clearing the record is not incidental. STORY-082 put it on the edition so that an edition
holding zero obligations can say *why*. Left standing it would read "Built 2026-08-30 with
extractor `local`" directly above "No obligations recorded for this edition" — a build whose
output no longer exists, described in the past tense as though it did, which is the same
three-way ambiguity STORY-082 closed, restored by the back door. `build_state IS NULL` is
already the encoding for never-built, and after a re-ingest that is what the edition is:
freshly chunked text with nothing extracted from it.

**This does not narrow [ADR-007](ADR-007-sources-describe-documents.md).** "Ingest is
additive" governs documents, their `DESCRIBES` edges, and the external/non-external promotion
that goes with them. The derived layer has never been additive — replacing an edition's chunks
was already destructive, and this makes the layer above them follow the same rule instead of
being silently detached from it.

## Consequences

**Makes easy.** The graph can no longer hold an obligation that no query can produce. `total`
and `returned` agree by construction, so a screen cannot report clauses it is unable to show,
and Triage cannot rank changes over them.

**Makes hard.** Re-ingesting a built edition now visibly costs its extraction — about an hour
of model time for a 38-chunk edition — where before it appeared to cost nothing and in fact
cost the same. The loss is not new; only its visibility is. Anyone re-ingesting to pick up a
chunker fix must plan to rebuild afterwards, and the README says so where it describes building
a derived layer.

**Commits us to.** Dropping, not repairing, whenever the text under a derived layer is
replaced. Any future path that rewrites chunks — a new source format, a re-scan, a migration —
inherits this obligation, and the ordering in `links/rebuild.py` and `ingest.py` is the two
places that show what it looks like. A third would be worth a shared helper.
