# Sprint 11 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next one
> ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 10 asks this session to settle

**The prompt contradicts itself in two places.**
[STORY-103](../../backlog/stories/STORY-103-the-prompt-stops-contradicting-itself.md) is Ready at
S. It was not fixed when found because correcting the prompt bumps `PROMPT_VERSION` and discards
the extraction cache, and three rebuilds were in flight. Nothing is in flight now.

**`ASSIGNED` is slightly under the hand count and nobody has read which two are missing.** 19
against 21 on DoDD 5000.01 (2020). Sprint 9 closed with this number unverified in the other
direction and sprint 10 verified only the excess.

**Two editions have a source file and no obligations.** DoDD 5000.01's Change 1 edition, and
DoDM 8180.01 at 204 chunks — several hours of extraction. That is new coverage rather than
correcting false data, which is why sprint 10 left it.

**The quotation invariant is verified once, not continuously.** A CI test over the integration
harness would be vacuous, because its stub extractor produces quotations by construction. An
honest limit and an unsolved problem.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) holds STORY-103 (S).

[Refining](../../backlog/backlog.md#refining) holds STORY-035, still blocked because no `.docx`
exists in `data/samples` to design against.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023 and STORY-045.
STORY-021 — which entities a policy applies to, and who enforces it — now has a stated
prerequisite from [ADR-035](../../specs/adr/ADR-035-an-actor-is-validated-before-it-is-canonicalised.md):
nothing measures actor accuracy, and canonicalising a field nothing scores would repeat the mistake
ADR-034 was written to undo.
