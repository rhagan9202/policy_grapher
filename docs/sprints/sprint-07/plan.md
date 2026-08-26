# Sprint 7 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next
> one ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 6 asks this session to settle

From sprint 6's [review](../sprint-06/review.md) and
[retrospective](../sprint-06/retrospective.md):

- **The corpus numbers in the README were measured against PROMPT_VERSION 1 output**, which
  included section headings extracted as obligations. 113 obligations, 265 proposals, the triage
  counts — all of them describe output the extraction gate would now reject. Re-run and correct
  them.
- **Decide what a `PROMPT_VERSION 1` obligation is worth.** Editions built before 2026-08-26 hold
  obligations produced by a prompt since proven to write headings and to drop sentence subjects.
  Their `obligation_id`s hash those statements, so re-extraction re-keys them and
  [ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md)'s re-pointing applies. No
  review decisions exist yet, so the cost is low today and rises with every verdict recorded.
- **Schema rejections roughly tripled.** PROMPT_VERSION 2 buys precision 0.294 → 0.625 and recall
  0.385 → 0.769, and costs a rejection rate that moved from 2 in 37 to roughly 1 in 5 — each one
  losing a whole chunk to `modality: null` on sentences that state scope rather than duty. Three
  prompt variants were tried against it and none helped, so this is a real trade rather than a
  wording problem. Whether a single unparseable *item* should cost its chunk, or only itself, is
  the question [ADR-023](../../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)
  answered once at the chunk boundary and may need to answer again at the item boundary.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) is empty again — all six of sprint 6's items are in Done.
[Refining](../../backlog/backlog.md#refining) holds STORY-014, STORY-031, STORY-035 (blocked: no
DOCX sample), STORY-036, STORY-047, STORY-073 and STORY-076.
[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023, STORY-045 and
STORY-075.

The planning review that opened sprint 6 also surfaced items nobody has filed: the rebuild status
poll runs on a flat two-second timer with no backoff, which at the eight-hour job timeout is
roughly 14,400 requests per open tab per run; Review's empty state is a false all-clear of the
shape STORY-067 fixed on Triage; and `merge_authority`, `attach_authority` and `merge_entity` in
`versions.py` have no production caller.
