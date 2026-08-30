# Sprint 12 — Plan

**Dates:** 2026-08-30 → TBD · **Capacity:** one working session

*Dated record — written at sprint start, not edited afterward.*

## Goal

**A change to the extractor shows what it did, everywhere — not only where somebody thought to
look.**

Sprint 9 taught the product to read duties assigned by position. Sprint 10 stopped it reading them
wrongly. Sprint 11 took that section from 19 of 40 items to 34. Each of those three sprints also
broke a passage it was not touching, and each was caught only because the broken passage happened
to be one of eight gold fixtures.

That is the thing to fix this sprint. Not the coverage that remains — which is real, and committed
below — but the fact that **this project cannot currently tell what a prompt change did.**

## The evidence this goal rests on

| Sprint | The edit | What broke, elsewhere |
| --- | --- | --- |
| 9 | Replaced the ASSIGNED example with a fictional office | That fixture went 5 of 5 to **0 of 5** |
| 10 | Added the quotation instruction | Precision fell to **0.800**, under its floor |
| 11 | Added a block teaching two role heading forms | An unrelated passage entered a **repetition loop** — 25 statements, 6 distinct, invalid JSON |

Sprint 11 established the mechanism by measurement rather than suspicion: the block that taught
paragraphs 2.6 and 2.7 was also what made an unrelated passage loop, and compressing it to a third
its size fixed both. **A 5,700-character prompt has non-local effects on an 8B model.** Nothing
introduced that; it is what the file is.

The gold set is eight fixtures against 580 chunks. It is a correctness check and it was never
designed to be a blast-radius check, which is why all three escapes were luck.

## Committed

Three items: 1L + 2M. The L is the goal; the two M items are a coverage debt and a decision
prerequisite that have each been deferred once with a written reason.

| ID | Item | Size | Why it is here |
| --- | --- | --- | --- |
| [STORY-107](../../backlog/stories/STORY-107-a-prompt-change-shows-its-blast-radius.md) | A prompt change shows its blast radius before it ships | L | The goal. A differential check over real chunks, needing no labels |
| [STORY-106](../../backlog/stories/STORY-106-a-positional-duty-is-not-labelled-shall.md) | A positional duty is not labelled SHALL | M | Paragraphs 2.5 and 2.10 read zero — 5 of the 6 items missing from 34 of 40 |
| [STORY-108](../../backlog/stories/STORY-108-actor-accuracy-is-measured.md) | Actor accuracy is measured | M | ADR-035 named this as the prerequisite for revisiting actors, and nothing has closed it |

**STORY-107 and STORY-106 are ordered deliberately.** STORY-106 is a prompt change, and STORY-107
is the thing that would show what that prompt change did. Building the check first means the
sprint's own riskiest edit is the first thing measured by it — which is a better demonstration
than any test written against a remembered failure.

**If one slips it is STORY-108**, which is measurement rather than capability and blocks only work
nobody has scheduled.

## What sprint 12 already knows

**Actor accuracy, measured at planning over the gold set's 25 matched pairs:** 0.600 exact, **0.840
case-folded**. Six of the ten disagreements are case alone. Every one of the remaining four is
`DIRECTOR OF OPERATIONAL TEST AND EVALUATION` against the gold set's `DOT&E` — the heading reads
`2.7. DIRECTOR OF OPERATIONAL TEST AND EVALUATION (DOT&E).`, the model took the title and the
fixture took the abbreviation, **and both are defensible.** STORY-108 is therefore a question about
what the gold set should say before it is a question about the extractor, and the story says so.

**What the deferred coverage would cost**, measured at planning so it stops being a vague "several
hours":

| Edition | Chunks | Offered | Cold estimate |
| --- | ---: | ---: | ---: |
| DoDD 5000.01 Change 1 | 41 | 37 | ~0.8h |
| DoDM 8180.01 | 204 | 188 | ~3.9h |

Nearly five hours of extraction for coverage of two editions that currently hold no false data.
Deferred again, and now with a number attached rather than an impression.

## Risks

**STORY-106 may not be solvable without reopening the loop.** The trade is written into the story:
more prompt recovers paragraphs 2.5 and 2.10 and risks looping elsewhere. If STORY-107 lands first
and shows the loop returning, **that is a successful sprint even if STORY-106 fails** — the check
will have done in one session what took three sprints of accidents to notice.

**A differential check reports change, not badness.** Any real prompt edit moves numbers, so this
cannot be a pass/fail gate, and a report nobody reads is worth nothing. The story's last acceptance
criterion — that the diff goes into the sprint review — is what stops it becoming a tool that
exists and is never run.

**Nothing here improves what the product reads**, except STORY-106's five items. Two sprints have
now been spent on trustworthiness rather than capability, and the review should be honest about
whether that is still the right trade or has become a habit.

## Definition of Done

The [standing gates](../../backlog/README.md#definition-of-done), plus what sprints 9 to 11 added:

- Acceptance criteria read against the code, and for coverage against the document.
- Every new test mutated before it is believed.
- An anomaly is a hypothesis about the measurement first — checked with the code's own function.
- **A conclusion inherits the errors of the measurement it came from.** Sprint 11 corrected a
  standing action that had been derived from two figures which turned out to be different builds.
- One model-bound job at a time.
- Verify a denominator before quoting a ratio against it.
