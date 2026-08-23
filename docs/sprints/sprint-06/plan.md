# Sprint 6 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next
> one ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

**The [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge) is over, and
[Ready](../../backlog/backlog.md#ready) is empty.** Sprint 5 delivered every refined item.
Nothing is pickable: this planning session has to start from
[Refining](../../backlog/backlog.md#refining) and [Ideas](../../backlog/backlog.md#ideas), and
each item has to meet the [Definition of Ready](../../backlog/README.md#definition-of-ready)
before it can be committed. That is a planning session's worth of work before any code, and
pretending otherwise is how an unrefined item becomes a mid-sprint surprise.

## What sprint 5 asks this session to settle

From sprint 5's [review](../sprint-05/review.md) and
[retrospective](../sprint-05/retrospective.md):

- **Re-measure the extraction ratchet's floors against the widened modality set.**
  [ADR-025](../../specs/adr/ADR-025-will-is-a-modality-and-bindingness-is-derived.md) records
  that it did not: the gate currently measures a model that was never asked for WILL against
  floors set before WILL existed. The gold set is now four fixtures and twelve obligations.
- **Extraction is roughly twice as slow as it was.** 104 seconds a chunk against ~45, because a
  widened set means far more to report. Any estimate reusing sprint 4's timings is wrong.
- **Push, so CI runs for the first time.** Three jobs, none ever executed — the push carrying
  them was rejected for want of `workflow` scope. Everything has been run command-by-command
  locally, which is not the same thing.
- **Read acceptance criteria back before closing a story**, and before its file is deleted.
  STORY-057 closed with two of four unmet.

## What the backlog holds

Nothing in Ready. [Refining](../../backlog/backlog.md#refining) holds STORY-014, STORY-031,
STORY-035 (blocked: no DOCX sample), STORY-036 and
[STORY-047](../../backlog/stories/STORY-047-reissues-read-as-replacement.md) — whose open
questions reopen a frozen decision in
[ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md), and which the roadmap
says is an ADR to write rather than a sprint item to commit. [Ideas](../../backlog/backlog.md#ideas)
holds STORY-020, STORY-021, STORY-023 and STORY-045.

The [vision](../../planning/vision.md#what-success-looks-like)'s two open MVP bars are DOCX
ingestion and XLSX manifests, both deliberately left out of the surge as feature work rather
than debt.
