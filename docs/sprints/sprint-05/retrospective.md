# Sprint 5 — Retrospective

**Date:** 2026-08-23 · **Participants:** —

*Dated record. Never edited — the value is in what the team believed at the time.*

## What we're changing

**1. Audit the thing you are claiming about, not the thing that is easy to enumerate.** The
plan's Definition of Done said "no client function in `api/client.ts` is left without a caller".
That check passes trivially against a client that never modelled a route at all — which is
exactly the state sprint 4's rebuild routes were in, and `GET /documents/{slug}/chunks` before
them. The claim was about *backend capability being reachable*; the check was about *client
functions being called*. From now on a reachability check compares the routers' declared paths
against the client. It is in `architecture.md` and it is three lines of Python.

**2. A story is done when its acceptance criteria are met, not when its headline behaviour
works.** STORY-057 was closed a day earlier with its first and fourth criteria met and its
second and third — "records how many items were rejected **and why**" and "rejected items are
visible to an operator without reading container logs" — not. Nothing failed; the feature
worked. It was found by re-reading the story, which is a step that should not depend on
remembering to take it. **Read the criteria back, line by line, before writing any item into a
review.**

**3. Record what a change costs in wall clock, not only whether it works.** STORY-055 took
extraction from ~45 seconds a chunk to **104**, because a widened modality set means far more to
report. That is the change succeeding. It also roughly doubles what a corpus rebuild costs, and
sprint 4's timings are now wrong in any plan that reuses them.

## What went well

- **Every DoD gate was walked in a browser, and it changed the result.** The plan added "every
  walkthrough step is a UI action" specifically so a `curl` walkthrough could not pass while the
  claim stayed untrue. Two defects came out of it, and STORY-061 — without which the sprint goal
  was unreachable — came out of preparing for it.
- **The suite caught the consequence of a schema change within a minute.** Adding `WILL` to
  `Modality` broke `test_every_modality_the_schema_allows_has_a_weight`, which asserts the
  Triage weight table's keys equal the enum's members. Someone wrote that guard for exactly this
  moment. Without it, every WILL obligation would have ranked at a silent fallback.
- **ADR-023 was written on 2026-08-22 and earned its keep on 2026-08-23.** Three real rebuilds
  rejected 2, 3 and 2 chunks. Under the previous behaviour each of those runs would have died
  and discarded everything before the failure.
- **The extraction cache was demonstrated end to end for the first time.** A re-run over
  unchanged content produced 265 proposals in under a minute against roughly an hour cold.
  ADR-013 claimed that; nothing had ever shown it.
- **The overcommit did not bite**, and the plan said in advance why it might not: five of eight
  items were UI work over an existing API. Recording the reasoning made the outcome readable
  rather than lucky.

## What didn't

- **The Definition of Done I wrote contained a check that could not fail in the way that
  mattered.** Change 1 above. It is the second sprint running where a check asserted something
  narrower than the claim it was standing in for — sprint 4's was ADR-020 tested against a
  developer's shell while compose supplied another model.
- **A story was closed with two of four acceptance criteria unmet, one day after adopting a rule
  about not closing unfinished work.** The rule was about sprints; the same reasoning applies to
  stories and was not applied.
- **Test assertions matched three cells per row, again.** Two DocumentTable tests failed because
  a document's name appears in its name cell, its references cell and its actions cell. Sprint
  3's retrospective recorded this exact pattern about `getByText`. Third occurrence.
- **`docs/backlog/stories/STORY-057-...md` was deleted when the story closed, and the criteria
  it held are the ones that turned out to be unmet.** Deleting it was correct by CONVENTIONS —
  a document that no longer describes reality goes — but it removed the checklist before anyone
  had checked against it.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Read acceptance criteria back line by line before writing any item into a review; do it before the story file is deleted | — | Sprint 6 |
| Sprint 6 planning starts from Refining and Ideas — Ready is empty and nothing meets the Definition of Ready | — | Sprint 6 planning |
| Re-measure the extraction ratchet's floors against the widened enum; ADR-025 records that they were not | — | Sprint 6 |
| Push, so CI runs for the first time. It needs `gh auth refresh -s workflow` | — | Immediately |

## Follow-up on last sprint's actions

**"Audit the remaining Settings fields for the ADR-020 gap."** Done as STORY-060, and it found
more than expected: not another instance of the same defect, but the gap ADR-020 had named in
its own text and left open. ADR-024 closes it.

**"Add one rebuild against the real extractor to the walkthrough."** Done, and it produced
three. It is the reason this sprint has real numbers for what extraction costs.

**"Take the modality decision."** Done as STORY-055 and ADR-025.

**"Add the compose-build CI job."** Done as STORY-059, with a size gate that fails if the
default image passes 1GB — ADR-021 undone.

All four carried actions were completed in the sprint they were assigned to, which is the first
time that has happened.
