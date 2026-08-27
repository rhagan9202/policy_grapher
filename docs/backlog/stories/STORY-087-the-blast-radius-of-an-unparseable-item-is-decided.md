# STORY-087: The blast radius of an unparseable item is decided

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a maintainer of the extraction pipeline, I want a written decision on whether one item a
model returns badly costs its whole chunk or only itself, so that the implementation that
follows is arguing from a recorded position rather than inventing one.

## Context

[ADR-023](../../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md) settled the
blast radius once, at the chunk boundary: one unparseable item costs its chunk, not the run.
That was a large improvement — before it, a single bad item ended a 38-chunk run and discarded
everything before the failure.

Sprint 6 made the cost of the remaining boundary visible. `PROMPT_VERSION 2` bought precision
0.294 → 0.625 and recall 0.385 → 0.769, and cost a rejection rate that went from **2 chunks in
37 to 8 in 37**. Every rejection is a whole chunk's obligations lost — not the one sentence the
model got wrong. Measured on the 2026-08-26 rebuild, that is roughly a fifth of the document.

The failures are not random. All eight were `modality: null` on sentences that state scope
rather than duty — "This issuance applies to the OSD, the Military Departments..." — where the
model has no modal verb to report and emits null rather than omitting the sentence. Three prompt
variants were tried against it in sprint 6 and none moved it, which is what makes this a
boundary question rather than a wording one.

**The decision is genuinely open**, which is why it is split out. Dropping the bad item and
keeping the chunk recovers four fifths of what is currently lost. It also weakens the property
ADR-023 relies on: `Modality` is closed *on purpose*, so that a model inventing a binding level
fails loudly rather than silently downgrading a duty. A rule that silently discards whatever
does not validate is one an adapter could hide behind.

## Acceptance criteria

- [ ] An ADR is written and committed that decides whether an item failing schema validation
      costs its chunk or only itself.
- [ ] It states what is given up either way, in particular what stops being loud if items are
      dropped silently, and how that is compensated.
- [ ] It says what a caller is told: a dropped item has to be counted and reportable, or the
      screen loses the ability to say an edition is incomplete — which is what STORY-057 was
      for.
- [ ] It records the measured numbers this decision rests on: 8 of 37 chunks, all
      `modality: null`, against 2 of 37 under the previous prompt.
- [ ] It supersedes or amends [ADR-023](../../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)
      explicitly rather than sitting beside it, since the two speak to the same boundary.

## Dependencies

- None. The measurement it argues from is in sprint 6's
  [review](../../sprints/sprint-06/review.md).

## Open questions

- Is "drop the item, count it, report it" enough, or does a chunk that loses items need to be
  re-extracted rather than accepted partial? Re-extraction is not free and the model is
  deterministic at temperature 0, so a second attempt returns the same answer — which argues
  the ADR should say so rather than leave a retry looking attractive.
