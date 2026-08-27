# Sprint 7 — Retrospective

**Date:** 2026-08-27 · **Participants:** —

*Dated record. Never edited — the value is in what the team believed at the time.*

## What we're changing

**1. A check written against literals is a check against literals. Measure the shape.** Sprint 6
verified that section headings had stopped being extracted by comparing five exact strings, and
reported zero. The same change that fixed the real defect had altered those strings — the model
had started keeping the closing full stop — so `'Be Responsive'` no longer matched `'Be
Responsive.'` and eighteen headings sailed through. The claim went into a dated record and stood
for a day.

What would have caught it costs nothing: **ask the question by shape rather than by example.**
`size(split(statement, ' ')) <= 4` finds every heading, including the ones nobody thought to
name. The same instinct applies everywhere this project has been bitten — the vacuous tests
sprint 6 found were all checks that named specific values instead of asserting a property.

**2. Ask what a change will do to existing data before running it, not after.** The extraction
cache held three entries written under the older schema, and a cache hit re-validates. Replaying
them would have raised, which `rebuild_derived` catches as a *chunk* rejection — silently
discarding valid obligations cached alongside a stale one, which is exactly the blast radius
ADR-030 had just moved.

It was found by querying the cache before starting the rebuild, and the whole cost was one
`MATCH ... CONTAINS` and two minutes. Found afterwards it would have looked like a mysterious
drop in a counts dict, days later, with the run already spent. **A schema change is a migration
even when nothing migrates**, and this project now has two stores that outlive their rules: the
graph and the extraction cache.

## What went well

- **The loop finally ran.** Ingest through to a ranked Triage row, every step a UI action, on
  obligations worth trusting — and the first human verdict this project has ever recorded
  survived two rebuilds. Three ADRs promised that behaviour and none had been watched doing it.
- **Splitting the decision from the implementation worked exactly as the backlog says it should.**
  STORY-087 wrote ADR-030 and STORY-088 implemented it, and because the decision was written
  first the implementation had an answer for every question that came up — including "what about
  a chunk where nothing validates", which is in the ADR and would otherwise have been invented at
  the keyboard.
- **The gates caught the sprint's own work again.** ADR-030's first wiring would have printed
  "0 chunks rejected" above eight entries; the reporting requirement in the ADR is what made that
  visibly wrong rather than merely untidy.
- **Making obligations readable keeps paying.** STORY-081 shipped last sprint, and this sprint the
  headings were spotted by *looking at the screen* — not by a test, not by a metric.

## What didn't

- **The correction was mine, in a record I wrote, about a defect class I had spent the previous
  sprint removing.** Sprint 6 found three vacuous checks and fixed them; then its own verification
  was one. Writing the rule down does not stop the author repeating it — this is the second
  retrospective in a row to say so, which suggests the remedy is mechanical rather than
  attentional.
- **STORY-082's AC7 shipped on an assumption about RQ that was never tested against RQ.** The
  criterion was written, the code was written to satisfy it, a test was written to match the code,
  and all three agreed with each other and not with the system. It took replacing a container by
  accident to find out.
- **The rejection rate is now the headline number and nobody chose it.** Twenty of thirty-seven
  chunks yield nothing. It is defensible — those chunks are headings and preamble the model
  over-extracts from — but the product's honest output halved in a sprint whose goal was to stop
  losing a fifth of it, and the reason is a different loss that was there all along.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Decide whether a 54% chunk-rejection rate is the model, the prompt, or the chunker — with the ratchet as the instrument, now that it can measure | — | Sprint 8 |
| When verifying that a class of thing is gone, assert the property, never a list of examples | — | Standing |
| Before a schema or validation change, query what the graph and the extraction cache already hold under the old rules | — | Standing |

## Follow-up on last sprint's actions

**"Re-run the corpus numbers in the README against PROMPT_VERSION 2 output."** Done as STORY-091,
and they moved further than expected because the modality rule landed in the same sprint.

**"Decide what a stale PROMPT_VERSION 1 obligation costs."** Answered by circumstance rather than
by decision: the 2026-08-26 rebuild had already dropped all of them, and no review decision
existed yet, so the migration this was meant to price never had anything to migrate. The window
closed today — the first `:LinkDecision` now exists, and every later extraction change has to
carry ADR-027's re-pointing.

**"Keep reading acceptance criteria back line by line."** Done, and it is now the third sprint
where it caught something.
