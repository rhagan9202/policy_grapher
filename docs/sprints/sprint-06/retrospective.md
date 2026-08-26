# Sprint 6 — Retrospective

**Date:** 2026-08-26 · **Participants:** —

*Dated record. Never edited — the value is in what the team believed at the time.*

## What we're changing

**1. A "this check did not run" announcement is itself a check, and needs its own test.** The
extraction ratchet carried two carefully written `THE EXTRACTION GATE DID NOT RUN` messages,
built so that a green suite could never be mistaken for a passing gate. A single table entry —
`FLOORS["null"] = {0.0, 0.0, 0.0}` — disarmed both, because a recorded entry made `floors is
None` false and the null adapter also bypassed the reachability skip. The messages were right
and unreachable, which is worse than not having written them: they made the gate look defended.

The fix that generalises is not "don't record zero floors". It is that **the loud-skip path must
be exercised under the configuration people actually run.** `Settings()` resolves to `null`, and
`null` is what CI runs, so that is the path to test. `test_no_recorded_floor_is_unfailable` now
does it, and it is written as a property — no adapter may carry floors nothing can score below —
rather than as a ban on one dict key.

**2. Reading acceptance criteria back line by line works, and it should stay.** Sprint 5's
retrospective assigned this here after STORY-057 closed with two of four criteria unmet. It
caught two things this sprint that nothing else would have. STORY-081's AC6 could not be met
until STORY-082 landed the build record, so the commit said so instead of claiming it, and the
copy hedged honestly until the data existed to be precise. STORY-084's AC3 — "the failure names
which leg fell and by how much" — had never actually been seen to fire, and reading it back is
what turned it into a mutation test rather than an assumption.

## What went well

- **The gates caught their own sprint's work.** STORY-086's reachability test flagged STORY-081's
  route within an hour of existing, with the message it was written to produce. A check that
  fires on the next thing you build is a check that works.
- **Fixing the extractor rather than the floor was the right call and was affordable.** The
  ratchet's own failure message says "Fix the extractor — do not lower the floor". Following it
  took three measured prompt passes and moved precision 0.294 → 0.625 and recall 0.385 → 0.769.
  Lowering the floors would have taken one line and rebuilt the vacuous gate that had just been
  removed.
- **Making obligations readable is what exposed the extraction defect.** STORY-081 shipped and
  the screen immediately showed section headings listed as obligations. The gate found it in the
  gold set the same afternoon; either alone would have been a weaker signal, and neither would
  have been visible a week ago.
- **The planning review was worth its cost.** Seven lenses over the plans, the code and the
  backlog produced three defects fixed before the sprint opened and a corrected estimation scale
  — and it was adversarial about work written the same morning, which is the part that mattered.

## What didn't

- **Three acceptance criteria written at planning were wrong, and one could not fail.**
  STORY-082 recorded only completed rebuilds while two of its own criteria needed in-flight and
  dead-worker state; STORY-083 asked that a file's "structure is obvious"; STORY-081 ordered by a
  property the schema does not store. All three were caught by the requirements review before
  commitment, but all three were written three days after a retrospective that made unfalsifiable
  checks its number-one change. **Writing the rule down did not stop the author repeating it.**
- **An intermittent test failure was nearly accepted as noise.** It appeared about one run in
  eight and passed six consecutive runs while being investigated. It took fourteen runs to
  reproduce, and the cause was real: `mockReset` drops a mock's implementation, leaving a window
  where an unflushed React effect calls a bare `vi.fn()`. An intermittent failure is worse than a
  red one — it teaches people to re-run rather than look.
- **The extraction quality this project has reported for two sprints was overstated**, and every
  number downstream of it — 113 obligations, 265 proposals, the triage counts in the README —
  was measured against output that included section headings. Nothing was lying; nothing was
  checking either.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Re-run the corpus numbers in the README against PROMPT_VERSION 2 output, and correct them | — | Sprint 7 |
| Decide what a stale `:Obligation` from PROMPT_VERSION 1 costs, and whether editions built under it need re-extraction to be trusted | — | Sprint 7 planning |
| Keep reading acceptance criteria back line by line, before the story file is deleted | — | Standing |
| Give the modality-accuracy leg a gold example per modality as new modalities are added — the enum comparison now fails until one exists | — | Standing |

## Follow-up on last sprint's actions

**"Read acceptance criteria back line by line."** Done, and kept — see change 2.

**"Sprint 6 planning starts from Refining and Ideas."** Superseded. A walkthrough on 2026-08-25
filed three Ready items before planning, and the planning review added three more.

**"Re-measure the extraction ratchet's floors against the widened enum."** Done as STORY-084,
and it found considerably more than a stale number.

**"Push, so CI runs for the first time."** Already done on 2026-08-24, and both this folder's
stub and sprint 5's retrospective still said it had never run. Six green runs at planning time.
