# Sprint 10 — Retrospective

**Date:** 2026-08-28

*Dated record — written at sprint close, not edited afterward.*

## What we're changing

**1. Before explaining a number, check the two figures measure the same thing.** Three times this
sprint I raised an anomaly that was my own measurement error, and each cost real attention:

- *"The second pass is not hitting the cache"* — it was. I sampled during the handful of chunks
  pass 1 had rejected, which cache nothing, and generalised from the slowest four.
- *"The 2003 edition gained obligations between passes"* — it did not. I compared
  `obligations_written`, a write count that `MERGE` then collapses, against a distinct-node count.
- *"One obligation still misquotes its chunk"* — none did. My verification query collapsed double
  spaces once instead of collapsing every whitespace run, unlike the `normalize()` the guard uses.

Each was announced before it was checked. The rule: **an anomaly is a hypothesis about my
measurement first and about the system second**, and the cheap discriminator — run the same input
through the same function the code uses — takes one command.

**2. Change one thing when a measurement is going to be read.** The quotation guard and the prompt
example were changed together, and when precision fell to 0.800 the number could not say which had
done it. I attributed it to the guard, publicly, and was wrong: reverting the prompt alone restored
every figure and the guard turned out to cost nothing at all — identical to six decimal places.
An hour was spent recovering an answer that isolating the variable would have given immediately.

**3. Order rule changes before the long-running job they invalidate.** ADR-035's actor rule landed
after the rebuild had started, so all three editions were rebuilt twice. The sprint plan flagged
"both M items end in a measurement" as a scheduling risk and I read it as being about duration.
It was about ordering.

## What went well

- **Refusing to accept a number found a defect.** DoDD 5143.01 reported 190 drops against 17
  written, and the obvious reading — that document is simply hard — was wrong. The investigation
  found the run reporting 20 reasons against 213 refusals with nothing saying the list was capped.
- **Every acceptance criterion was checked against the graph, not the extractor.** The story was
  written that way on purpose, and it is the difference between "the rules are enforced" and "the
  data obeys them". Sprint 9 proved the first; this sprint needed the second.
- **A story survived contact with its own evidence and changed shape.** STORY-100 asked whether
  actor fragmentation was one problem or two; reading the values showed the field was not holding
  what the question assumed, and ADR-035 decided something the story had not listed.
- **Enumerating found what reading could not.** Four sprints of reading the extraction prompt did
  not surface that two of its sentences contradict ADR-033. Listing the rules side by side found
  both in minutes.
- **The deferral was recorded rather than carried.** STORY-103 exists because fixing the prompt
  mid-sprint would have discarded three in-flight rebuilds. That is a reason, written down, not a
  thing someone would have had to remember.

## What didn't

- **Three self-inflicted measurement errors in one sprint**, all announced before being checked.
  See above; it is the first action for a reason.
- **The rebuild was run twice for a reason that was avoidable.**
- **`ASSIGNED` is now slightly under the hand count** — 19 against 21 on DoDD 5000.01 (2020) — and
  nobody has read which two are missing. Sprint 9 closed with the same number unverified in the
  other direction, and this sprint verified the excess without verifying the shortfall.
- **The quotation invariant is verified once, not continuously**, and the review says so. A CI test
  over the integration harness would be vacuous, because its stub extractor produces quotations by
  construction. That is an honest limit and also an unsolved problem.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Read the two positional duties `ASSIGNED` is now missing on DoDD 5000.01 (2020) | — | Sprint 11 |
| Fix the prompt's two self-contradictions (STORY-103), and re-measure the actor rate | — | Sprint 11 |
| An anomaly is a hypothesis about the measurement first — check with the code's own function | — | Standing |
| Change one thing when a number will be read from it | — | Standing |
| Order rule changes before the long job they invalidate | — | Standing |

## Follow-up on last sprint's actions

**"Verify the 31 recovered duties against the document before the number is quoted as coverage."**
Done, and it was the most valuable hour of the sprint: 8 of the 31 attributed USD(A&S)'s duties to
three other offices, and the cause was the prompt's own worked example being echoed. That produced
ADR-034, the 17% measurement, and everything this sprint did.

**"Decide what an actor is (STORY-100)."** Done as ADR-035, and the decision is that the question
was premature.

**"Set a floor from the lowest observation across processes, truncated, never rounded."** Held.
The floors were not re-measured this sprint because no prompt change landed — STORY-103 defers the
one that would have required it.

**"When a new test passes on its first run, mutate the thing it guards."** Held, four times.
