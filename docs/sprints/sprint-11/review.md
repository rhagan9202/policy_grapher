# Sprint 11 — Review

**Dates:** 2026-08-28 → 2026-08-30 · **Goal:** the responsibilities section is read whole, and the
number saying so is one somebody counted

*Dated record — written at sprint close, not edited afterward.*

## The goal, measured

**Met, and the number is now one somebody counted.**

| | Before | After |
| --- | ---: | ---: |
| Lettered items read, DoDD 5000.01 (2020) | 19 of 40 | **34 of 40** |
| Coverage | 0.475 | **0.850** |
| `ASSIGNED` obligations in the edition | 19 | **34** |
| Obligations in the edition | 56 | **62** |

Three role sections that returned nothing or almost nothing now return completely:

| Para | Office | Items | Before | After |
| --- | --- | ---: | ---: | ---: |
| 2.3 | USD(I&S) | 4 | 1 | **4** |
| 2.6 | DoD CIO | 6 | **0** | **6** |
| 2.7 | DOT&E | 4 | **0** | **4** |

The graph agrees with the standalone measurement paragraph for paragraph, which is the check worth
having: sprint 10 established that the rules being enforced and the data obeying them are different
claims.

## Committed items

| ID | Item | Size | Outcome |
| --- | --- | --- | --- |
| STORY-104 | ASSIGNED recognises the role headings DoD actually writes | M | Delivered |
| STORY-103 | The prompt stops contradicting itself about ASSIGNED | S | Delivered, in the same version bump |
| STORY-105 | Responsibilities coverage has a floor | S | Delivered — named at planning as the item expected to slip, and it did not |

## The extraction floors

Measured on the shipped prompt, **identical across six runs in two separate processes**:

| | Floor before | Measured | Floor now |
| --- | ---: | ---: | ---: |
| precision | 0.842 | 0.862 | **0.862** |
| recall | 0.888 | 0.893 | **0.892** |
| modality accuracy | 0.85 | 1.000 | 0.85 (held) |

**Recall rose while the gold set grew from 18 obligations to 28.** Ten harder examples added, and
the extractor found proportionally more than before — that is the sprint's claim in one number.

`COVERAGE_FLOOR` is **0.80** against a measured 0.850, deliberately not set at the observation:
over 40 items one item is 0.025, and a floor that fires on a single differing answer teaches people
to ignore it. Same reasoning as `modality_accuracy`, now applied a second time.

## Two defects found, one inside the other

**The adapter could not bound generation, and never could.** One gold fixture drove llama3.1:8b
past 3000 seconds on a single call — roughly 16,000 tokens at the observed 5.4 tokens/sec — while
`LocalExtractor`'s 600-second timeout and its three retries turned that into half an hour for one
chunk. **A timeout bounds waiting; it does not bound generating**, and nothing did. That gap
predates this sprint and any sufficiently awkward chunk in a real rebuild could have hit it.

`num_predict` now bounds it at 2048, sized from measurement rather than chosen round: every gold
fixture's legitimate answer was counted and the largest is 554 output tokens. **A cap of 1024 would
have truncated paragraph 2.6** — one of the two sections this sprint exists to recover — which is
why the number was measured first.

**The prompt looped, and the cap is what made it visible.** With the runaway failing in minutes
instead of hours, the gate failed at recall 0.679 against a floor of 0.888. The floor did not move.
Per-fixture scoring put 6 of the 9 missing obligations in one fixture; capturing its output showed
**25 statement fields and 6 distinct**, two of them repeated ten times each. A degenerate repetition
loop, not over-extraction — the model found the right answer and then repeated it until truncation.

Bisecting located it exactly: with STORY-104's block, 2048 tokens and invalid JSON; without it, 574
tokens and a clean stop. **The block that taught the two role heading forms was also what made the
model loop.** Compressed to a third its size, all three chunks terminate and both recovered sections
stay complete.

**The general finding is larger than the fix: this prompt is long enough that adding text degrades
an unrelated passage.** That is a property of the file rather than of any one edit, and nothing
currently detects it — the gate caught this only because the affected passage happens to be a
fixture. A real chunk of the same shape would have failed silently inside a rebuild.

## The echo is still attempted, and is now impossible

Paragraph 2.10 tried it. Two of its dropped items are the prompt example's own USD(A&S) sentences —
`"Executes the acquisition re…"` and `"Serves as an advisor in the…"` — being written into the CJCS
section, and [ADR-034](../../specs/adr/ADR-034-a-statement-is-a-quotation.md)'s quotation rule
refused both. The rebuilt graph contains **zero** such attributions.

This is a better result than a clean pass would have been. Had the graph simply come back clean, the
reasonable conclusion would have been that the behaviour stopped. It has not: **a section that
yields nothing is still where the model reaches for something plausible**, and the guard is what
stands between that and the graph. ADR-034 is load-bearing, not belt-and-braces.

## What is not done

**Paragraphs 2.5 and 2.10 still read zero**, and are 5 of the 6 items missing. The cause is
measured: the model quotes their items correctly and labels them `SHALL`, so each fails the
modality-word rule and ADR-030 correctly rejects the chunk. The prompt says not to, in as many
words.

**It is a trade, not an oversight.** The block that would emphasise the rule harder is the one that
caused the loop. This sprint chose the version that keeps the gate green and reads 34 of 40 over one
that might read 37 and fail. Filed as
[STORY-106](../../backlog/stories/STORY-106-a-positional-duty-is-not-labelled-shall.md) with the
trade written down so the next attempt starts from it.

## Two corrections to the record

**The hand count of 21 was wrong; the document contains 40.** Sprint 9's review, sprint 10's review
and two velocity rows all cite it. It came from the coarse regular expression sprint 9's spec
described as coarse and then used as a denominator anyway. Pointers were added to each of those
records at planning. Coverage at sprint 10's close was 19 of 40, not 19 of 21.

**Sprint 10's conclusion about cross-process nondeterminism was wrong.** That retrospective recorded
that "identical on three consecutive runs" is determinism within one process and not across two, and
made it a standing action. The evidence was precision measured at 0.842 and then 0.905 — but those
ran against *different builds*, before and after ADR-035's actor rule. A build change was read as
process nondeterminism. Measured properly this sprint, two processes of one build agree exactly
across six runs. The correction is recorded beside the floors, where the next person setting one
will read it.

## Definition of Done

- **Acceptance criteria met** — read against the code, and for coverage against the document.
- **Tests written and passing** — 385 unit tests, integration suite green, extraction gate green
  against raised floors.
- **Every new guard mutated** — the output cap's two halves, and the coverage denominator check.
- **Documentation updated in the same change** — this review, the backlog, two corrections.
- **Runs under `docker compose up` from a clean checkout** — the rebuild reported here was driven
  through the running application.
