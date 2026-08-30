# STORY-107: A prompt change shows its blast radius before it ships

**Epic:** — · **Status:** Ready · **Estimate:** L

## User story

As a maintainer editing the extraction prompt, I want to see which passages the edit changed, so
that I stop discovering a fortnight later that a rule about role headings broke a passage about
something else.

## Context

**Three sprints, three prompt edits, three unrelated passages degraded:**

| Sprint | The edit | What broke, elsewhere |
| --- | --- | --- |
| 9 | Replaced the ASSIGNED worked example with a fictional office | That fixture went from 5 of 5 to **0 of 5**; the model stopped recognising the form entirely |
| 10 | Added the quotation instruction | Precision fell to **0.800**, under its floor |
| 11 | Added a block teaching two new role heading forms | An unrelated WILL-dense passage entered a **repetition loop** — 25 statement fields, 6 distinct, 2048 tokens, invalid JSON |

Every one was found by the extraction gate, and **only because the affected passage happened to be
one of eight gold fixtures.** A real chunk of the same shape fails inside a rebuild, silently, and
the coverage floor added in sprint 11 would not see it either — that floor watches one section of
one document.

Sprint 11 established the underlying property by measurement rather than suspicion: **this prompt
is long enough that adding text has non-local effects.** The block that taught paragraphs 2.6 and
2.7 was also what made an unrelated passage loop, and compressing it to a third its size fixed both.
That is not a bug anyone introduced; it is what a 5,700-character prompt does to an 8B model.

## What this is, and what it is not

**A differential check, not a correctness check.** It does not need labels, which is the point —
gold fixtures cost hours to transcribe and there are eight of them against 580 chunks. It records
what the current prompt produces on a fixed sample of *real* chunks and reports what moved when the
prompt changes.

**It reports, it does not judge.** A change that improves a passage flags exactly as loudly as one
that breaks it. That is correct: the reviewer wants to see the blast radius and decide, and a check
that tried to distinguish improvement from regression without labels would be guessing.

## The decision this needs

**L because three things are undecided and each has a real trade.**

- **Which chunks, and how many.** One edition is 37 chunks and roughly 45 minutes; a curated set
  spanning the shapes that have broken — WILL-dense prose, a responsibilities section, front
  matter, a definitional passage — might be 20 and half that. A larger sample catches more and is
  run less often, which may mean it is not run.
- **What to record.** Obligation count per chunk is the minimum. Token count and `done_reason`
  catch the sprint 11 failure specifically, since the loop showed as `done_reason: length` long
  before it showed as a score. Statement text would catch a quiet re-wording that keeps the count.
- **A test or a tool.** A test fails a build, which is the only thing that reliably gets run — but
  this cannot be a pass/fail gate, because any prompt change legitimately moves numbers. Most
  likely a script plus a committed baseline, run when `PROMPT_VERSION` changes, with the diff
  pasted into the review.

## Acceptance criteria

- [ ] A committed baseline records what the current prompt produces for each chunk in the chosen
      sample, including at least obligation count and `done_reason`.
- [ ] A command re-runs the sample and reports per-chunk differences against the baseline.
- [ ] It is demonstrated against sprint 11's actual failure: restoring the long prompt block must
      show the WILL-dense passage changing, and the report must make that visible without anyone
      knowing in advance to look at that passage.
- [ ] The baseline is regenerated as part of a deliberate prompt change and the diff is recorded in
      the sprint review, so the blast radius is part of the record rather than a thing someone saw
      once.
- [ ] It says how long it takes to run. A check nobody runs because it is slow is not a check, and
      naming the cost is what lets the sample size be argued about honestly.

## Dependencies

- None.

## Open questions

- Does this belong to the prompt or to the adapter? The same non-locality would appear on a
  different model with the same prompt, and swapping the model is a change this project intends to
  make eventually ([ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)).
- Is there a cheaper proxy than re-extraction? Sprint 11's loop was visible in `done_reason` and
  token count, both of which come back on every call — recording them during a *normal rebuild*
  would give a baseline for free, at the cost of only covering documents somebody rebuilt.
