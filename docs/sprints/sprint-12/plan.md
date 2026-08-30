# Sprint 12 — Plan

**Dates:** TBD · **Capacity:** TBD

*Dated record — written at sprint start, not edited afterward.*

> **This is a stub, not a plan.** The folder exists because closing a sprint creates the next one
> ([CONVENTIONS](../../CONVENTIONS.md#what-to-update-when)).
>
> **TODO:** hold the planning session, then replace this file wholesale.

## What sprint 11 asks this session to settle

**Two role sections still read zero.** Paragraphs 2.5 (CMO) and 2.10 (CJCS) of DoDD 5000.01 (2020),
5 of the 6 items missing from 34 of 40.
[STORY-106](../../backlog/stories/STORY-106-a-positional-duty-is-not-labelled-shall.md) is Ready at
M, and the trade is written down: the prompt block that would emphasise the rule harder is the one
that caused a repetition loop.

**Nothing detects a prompt change's non-local effects.** Three sprints running, an edit to the
extraction prompt has degraded a passage it had nothing to do with — a fixture from five of five to
zero, precision to 0.800, and a repetition loop. All three were caught only because the affected
passage happened to be a gold fixture. **This prompt is long enough that adding text has non-local
effects, and that is now a measured property rather than a suspicion.**

**Two editions have a source file and no obligations.** DoDD 5000.01's Change 1 edition, and
DoDM 8180.01 at 204 chunks. New coverage rather than correcting false data, which is why sprints 10
and 11 both left it.

**`:Entity` is still blocked on the same prerequisite.**
[ADR-035](../../specs/adr/ADR-035-an-actor-is-validated-before-it-is-canonicalised.md) deferred
canonicalising actors until something scores them, and nothing does. Sprint 11 added a second
actor spelling to the pile without meaning to: paragraph 2.6 returns
`DOD CHIEF INFORMATION OFFICER`, as its heading writes it.

## What the backlog holds

[Ready](../../backlog/backlog.md#ready) holds STORY-106 (M).

[Refining](../../backlog/backlog.md#refining) holds STORY-035, still blocked because no `.docx`
exists in `data/samples` to design against.

[Ideas](../../backlog/backlog.md#ideas) holds STORY-020, STORY-021, STORY-023 and STORY-045.
