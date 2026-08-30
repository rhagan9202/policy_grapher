# Sprint 11 — Retrospective

**Date:** 2026-08-30

*Dated record — written at sprint close, not edited afterward.*

## What we're changing

**1. Verify a denominator before quoting a ratio.** Planning began with sprint 10's action to read
the two duties `ASSIGNED` was missing, and found there were not two — the document holds 40 items
and the product read 19. The "21" that two sprints had measured against came from a regex sprint
9's own spec called coarse. Sprint 10's retrospective already says an anomaly is a hypothesis about
the measurement first; **the denominator was never a measurement at all**, and nobody had thought
to check it because it was not anomalous, merely wrong.

The fix is in the code, not the habit: `test_the_hand_count_still_matches_the_document` asserts the
expected counts against the document, needs no model, and runs in the fast suite. Had it existed at
sprint 9, the 21 would never have reached a review.

**2. A conclusion drawn from a measurement needs checking as much as the measurement.** Sprint 10
concluded that runs are deterministic within a process but not across two, and made it a standing
action. The two figures behind it were different *builds*. That conclusion then shaped how this
sprint set its floors, until two processes of one build were measured and agreed exactly.

I applied "check the measurement" to individual numbers all sprint and never applied it to the
conclusion I had drawn from them a sprint earlier. **A standing action is a measurement's
descendant and inherits its errors.**

**3. Do not start a second model-bound job while one is running.** Ollama serialises, so two jobs
interleave and both slow down — and the failure being chased was a *timeout*, so adding contention
was the worst possible thing to do to it. I had named this risk two steps before creating it, and
the probe I started had already been answered by an earlier census.

## What went well

- **The diagnosis chain held, every link measured.** Gate fails at 0.679 → per-fixture puts 6 of 9
  in one fixture and the arithmetic closes → output capture shows 25 statements and 6 distinct, so
  a loop rather than over-extraction → bisect isolates the block → compression fixes it and keeps
  both recovered sections. Nothing in that chain was inferred, and the one place I would previously
  have guessed — "the cap broke recall" — was wrong and the measurement said so.
- **The cap paid for itself immediately and not in the way intended.** It was written to stop a
  50-minute hang. What it actually did was convert an invisible failure into a fast, legible one,
  which is the only reason the loop was found at all.
- **Measuring before choosing a number.** The token census showed the largest legitimate answer is
  554 tokens. The round number I would have picked — 1024 — would have truncated paragraph 2.6,
  one of the two sections this sprint exists to recover.
- **The echo was caught by a guard rather than by luck.** Paragraph 2.10 attempted it and ADR-034
  refused it. A clean graph alone would have suggested the behaviour stopped; the drops show it has
  not, and that is a more useful thing to know.
- **The item named at planning as most likely to slip did not slip.** STORY-105 shipped, and its
  denominator check is the guard that would have prevented this sprint's own opening correction.

## What didn't

- **Two corrections to previously published records in one sprint**, both mine, both from numbers
  I had reported with more confidence than the evidence carried.
- **A prompt edit degraded an unrelated passage, for the third time in three sprints.** Sprint 9
  took a fixture from five of five to zero; sprint 10 saw precision fall to 0.800; this sprint drove
  a fixture into a repetition loop. Each was found and fixed, and **nothing detects the class**.
  The prompt is long enough that adding text has non-local effects, and the only reason all three
  were caught is that the affected passages happened to be fixtures.
- **Paragraphs 2.5 and 2.10 still read zero**, and the sprint closes with 34 of 40 rather than 40.
  The reason is recorded and the trade is written down, but a section reading zero is exactly the
  condition that invites the echo.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Recover paragraphs 2.5 and 2.10 without reopening the loop (STORY-106) | — | Sprint 12 |
| Decide whether a prompt change can be checked for non-local effects before it ships | — | Sprint 12 |
| Verify a denominator before quoting a ratio against it | — | Standing |
| A conclusion inherits the errors of the measurement it came from — re-check both | — | Standing |
| One model-bound job at a time | — | Standing |

## Follow-up on last sprint's actions

**"Read the two positional duties ASSIGNED is missing."** Done, and it invalidated the premise:
there were not two, there were 21, and the number they were measured against was wrong.

**"Fix the prompt's two self-contradictions (STORY-103)."** Done, in the same version bump as
STORY-104 so one re-extraction served both.

**"An anomaly is a hypothesis about the measurement first."** Held for individual numbers — the
cap, the loop and the bisect were all measured rather than guessed. Not held for the conclusion
sprint 10 drew about determinism, which is why it is now a sharper action above.

**"Change one thing when a number will be read from it."** Held once and broken once: the prompt
and the gold set changed together, which was unavoidable since the fixtures define the denominator,
but it meant the first failing measurement could not immediately say which had moved it.

**"Order rule changes before the long job they invalidate."** Held. Every prompt change landed
before the rebuild, and the rebuild ran once.
