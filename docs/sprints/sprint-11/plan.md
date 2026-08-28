# Sprint 11 — Plan

**Dates:** 2026-08-28 → TBD · **Capacity:** one working session

*Dated record — written at sprint start, not edited afterward.*

## Goal

**The responsibilities section is read whole, and the number saying so is one somebody counted.**

Sprint 9 made the product able to read duties assigned by position. Sprint 10 made it stop reading
them wrongly. This sprint is about how many of them it reads at all, which nobody has correctly
measured until this planning session.

## The correction this sprint opens with

**Sprint 9's review, sprint 10's review and two velocity rows all cite a hand count of 21
positional duties in DoDD 5000.01 (2020). That number is wrong. The document contains 40.**

Those are dated records and are not edited; this is where the correction lives, and a pointer has
been added to each so a reader arrives here.

The 21 came from the same regular expression sprint 9's spec described as "deliberately coarse" and
then used as a denominator anyway: it counts lettered lines opening with a capitalised
third-person verb, so it misses gerund items entirely and cannot tell which role heading an item
sits under. **Counting the lettered items under each role heading gives 40, and the product
currently reads 19 — 48%.**

That the error survived two sprints is the more useful finding. Sprint 9 measured coverage and
called the excess a defect; sprint 10 verified the excess and left the shortfall unverified; both
compared against a number neither had checked. The retrospective's action about anomalies being
hypotheses about the measurement applies here in its strongest form — **the denominator was never
verified at all.**

## What the 48% is made of

| Para | Office | In the document | Read | |
| --- | --- | ---: | ---: | --- |
| 2.1 | USD(A&S) | 5 | 6 | one extra sentence inside item e |
| 2.2 | USD(R&E) | 7 | 5 | |
| 2.3 | USD(I&S) | 4 | 1 | |
| 2.4 | USD(P&R) | 0 | 1 | prose, no lettered items |
| 2.5 | CMO | 2 | 0 | |
| 2.6 | DoD CIO | 6 | **0** | |
| 2.7 | DOT&E | 6 | **0** | |
| 2.8 | DCAPE | 4 | 4 | |
| 2.9 | DoD Component Heads | 3 | 1 | |
| 2.10 | CJCS | 3 | **0** | |

**The cause is diagnosed and it is not the guards.** Extracting paragraph 2.6 directly, the model
quotes its items correctly and labels every one `SHALL`. No `shall` is present, the modality-word
rule refuses each item, nothing survives, and ADR-030 correctly makes the chunk a rejection. The
duties are being read and thrown away for carrying the wrong label — which is also why those three
sections were where the prompt's worked example got echoed in sprint 9. **A section that yields
nothing is where a model reaches for something plausible.**

It is syntactic. The prompt teaches one form of role heading; DoD writes three. A lead-in clause
before the role (2.3, 2.6, 2.10) and a sentence ending `by:` with gerund items (2.7) both defeat it.

## Committed

Three items: 1M + 2S. Small, because the two prompt items share one `PROMPT_VERSION` bump and
therefore one full re-extraction and one re-measurement, and that is most of the session.

| ID | Item | Size | Why it is here |
| --- | --- | --- | --- |
| [STORY-104](../../backlog/stories/STORY-104-assigned-recognises-the-role-headings-dod-writes.md) | ASSIGNED recognises the role headings DoD actually writes | M | The goal. 18 of the 21 unread items sit in the four dead sections |
| [STORY-103](../../backlog/stories/STORY-103-the-prompt-stops-contradicting-itself.md) | The prompt stops contradicting itself about ASSIGNED | S | Same file, same version bump. Doing it separately costs a second two-hour re-extraction for nothing |
| [STORY-105](../../backlog/stories/STORY-105-responsibilities-coverage-has-a-floor.md) | Responsibilities coverage has a floor | S | Named at planning as the item expected to slip |

**STORY-105 is the one to drop if the session runs long.** It is also the only one that would stop
this happening again, which is an uncomfortable pairing and is recorded rather than resolved: a
coverage floor needs a hand-counted denominator per document, and hand-counting is exactly what
nobody did for two sprints.

## Risks

**This is the change most likely to bring the echo back.** Paragraphs 2.6, 2.7 and 2.10 currently
yield nothing, and they are where the model previously wrote USD(A&S)'s duties. Teaching it to find
duties there without teaching it to invent them is the whole difficulty. ADR-034's quotation rule
is the structural protection and it held; the acceptance criteria assert the regression stays
fixed rather than assuming it.

**A prompt change moves every number.** Sprint 9 saw a prompt edit take a fixture from five of five
to zero. Both prompt items land together and are measured together, and if the floors move the
review says so — **truncated below the lowest observation, never rounded to it.**

**48% may not become 100%, and that is allowed.** Paragraph 2.9's items are conditions on a
delegation rather than duties, and 2.4 has no lettered items at all. The target is that every
section the document writes as a role assignment is read, not that a number reaches 40.

## Definition of Done

The [standing gates](../../backlog/README.md#definition-of-done), plus the two sprint 9 added and
the three sprint 10 added:

- Acceptance criteria read against the code, and for coverage against the document.
- Every new test mutated before it is believed.
- An anomaly is a hypothesis about the measurement first — checked with the code's own function.
- One thing changed when a number will be read from it.
- Rule changes ordered before the long job they invalidate.
