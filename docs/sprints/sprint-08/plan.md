# Sprint 8 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next
> one ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 7 asks this session to settle

**The rejection rate is the open question, and it is now measurable.** Twenty of thirty-seven
chunks yield no obligation at all, because the model returns items and none of them contain the
modality they are labelled with — headings, scope statements, preamble. That is the model
over-extracting, not the documents being empty. Whether the remedy is the prompt, the model, or
the chunker is undecided, and the extraction ratchet can now tell the difference: it measures
precision, recall and modality accuracy separately, against a five-fixture gold set, and it fails
when it should.

**The window on cheap re-extraction has closed.** The first `:LinkDecision` exists as of
2026-08-27. Every change to extraction from here re-keys obligations and has to carry
[ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md)'s re-pointing, and a rebuild
now reports `promoted` and `unpromotable` for reasons that matter to a person.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) is empty — all six of sprint 7's items are in Done.

[Refining](../../backlog/backlog.md#refining) holds STORY-014 (search) and STORY-036 (XLSX
manifest), **which are the two remaining closable MVP bars** and were deliberately excluded from
sprint 7 because they did not serve its goal. They are the obvious spine of this one. Also
STORY-031, STORY-035 (still blocked: no DOCX sample exists in the repo), STORY-047, STORY-073 and
STORY-076.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023, STORY-045 and
STORY-075.

## Standing actions carried here

From sprint 7's [retrospective](../sprint-07/retrospective.md): when verifying that a class of
thing is gone, assert the property rather than a list of examples; and before a schema or
validation change, query what the graph and the extraction cache already hold under the old
rules. Both are written as standing rather than one-sprint actions because both were earned by a
defect that had already been fixed once.
