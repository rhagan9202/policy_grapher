# Sprint 10 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next one
> ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 9 asks this session to settle

**The headline number is unverified.** DoDD 5000.01's 2020 edition yielded 31 obligations assigned
by position against a hand count of 21. The six offices match the ones the document names, so this
is not wholesale invention — the excess is most likely additional duty-bearing sentences inside
lettered items. Nobody has read the 31 against the document. Until someone does, "31 duties
recovered" measures what the extractor emitted, not what the section contains, and
[sprint 9's review](../sprint-09/review.md) says so rather than quoting it as coverage.

**An office is not yet one thing.** `USD(A&S)` and `The USD(A&S)` are the same office and two
actors, and one actor is the fragment `acquisition executive`. `actor` has been free text on every
modality since extraction shipped, and it did not matter much while a duty was found by its modal
verb. A positional duty is *defined* by the office it is assigned to, so the field is now
load-bearing — and it is the field the roadmap's Later section wants to build `:Entity` over.
[STORY-100](../../backlog/stories/STORY-100-an-office-is-one-actor-not-several-spellings.md) is L
because the shape is undecided.

**A quarter of positionally-shaped items are still refused by design.** 151 sit in a section
titled RESPONSIBILITIES and 49 elsewhere, chiefly PROCEDURES in DoDI 8500.01. ADR-033's guard
refuses all 49, deliberately, precision over recall. Widening it is a new decision and now has a
measured number to argue from.

**Scale is still untested.** Every measurement this project has published is against 23 documents
while the manifest names 438, and sprint 9's goal was chosen over scale on the grounds that
measuring an extractor which could not see half the duty-bearing text would produce a confident
number describing half the truth. That objection no longer applies.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) is empty — all four of sprint 9's items are in Done.

[Refining](../../backlog/backlog.md#refining) holds STORY-100 (L, above) and STORY-035, still
blocked because no `.docx` exists in `data/samples` to design against.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023 and STORY-045. The
first two are the Policy Concierge schema, which sprint 9 fed without committing to: every
ASSIGNED obligation now carries the office it is assigned to, which is the raw material STORY-021
has always needed and never had.
