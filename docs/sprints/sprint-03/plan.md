# Sprint 3 — Plan

**Dates:** 2026-08-21 → 2026-08-21 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

**Revised once, at planning time, before any implementation began.** The design session for STORY-048 produced two decisions that invalidated the first draft: the derived-layer route needs an execution model this sprint cannot settle in passing, and the first run should be empty rather than seeded. Rewriting a plan we had already agreed was wrong beat executing it — but the revision happened before a line of code, and there will not be a second one.

First sprint in the [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge), and the
first in this project's history where every committed item carries an estimate. The
[t-shirt scale](../../backlog/README.md#estimation) and the
[cadence](../README.md#cadence) were both decided at this planning session, closing three
standing `TODO:` markers that sprints 1 and 2 each carried forward.

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

The app tells the truth about its own state: it starts empty, says so on every screen instead
of rendering blanks that read as failure, and carries none of the UI defects the 2026-08-21
audit found.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-049 | A cold start is empty, and the app says so instead of looking broken | M | — |
| STORY-039 | The graph view fits the window it is drawn in | S | — |
| STORY-040 | Triage only offers comparisons it can actually carry out | S | — |
| STORY-041 | The app has a favicon | S | — |
| STORY-038 | Creating a document through the API is one transaction | S | — |
| STORY-050 | The codebase contains no code the application cannot reach | S | — |
| STORY-053 | Planning documents describe the running app, not its library | S | — |

**Total committed:** 1M + 6S. Seven items against an observed 13 and 7 in sprints 1 and 2.
No L: the one L originally committed here — STORY-048 — moved to sprint 4 during planning,
because it contains an execution decision that needs a spec rather than a session, and
[the estimation note](../../backlog/README.md#estimation) says an L carrying an unmade
decision is a warning rather than a plan.

**STORY-053 is committed last on purpose.** It rewrites the claims in `roadmap.md` and
`architecture.md` to match reality, and reality is what the six items above it change.

## Why this order

**STORY-049 first, because it is the sprint's goal in one item.** Everything else is a defect
fix; this is the behaviour change. Flipping `AUTO_INGEST` to false is a one-line edit — the
work is the five empty states, and each has to distinguish *no corpus* from *nothing to do*.
Review's current "Nothing is waiting for review" is the example: true, and misleading, when
there are no documents at all.

**STORY-039, 040 and 041 pulled forward from sprint 4.** All three are defects in screens
STORY-049 rewrites. Fixing Triage's pickers while adding Triage's empty state is one piece of
work; doing them in different sprints means touching the same file twice and reviewing it
twice.

**STORY-038 is here because it is a known silent-corruption bug, not because it is related.**
It has sat in Refining since sprint 2's review deferred it, `architecture.md` lists it first
under *Known weak points*, and it blocks STORY-044 in sprint 5.

**STORY-050 is narrowed.** Its cache half belongs to STORY-048 in sprint 4. What is left is a
deletion decision on four genuinely unreachable symbols.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done), one addition
specific to this goal, because it is the thing the suite cannot check:

- [ ] **A cold-start walkthrough is performed and recorded in the review**:
      `docker compose down -v && docker compose up -d --build`, then every screen opened in a
      browser. The bar is that an empty app looks *deliberately* empty — a new arrival can
      tell nothing is wrong and knows what to do next. Not a test run; an observation, of the
      kind sprint 2's review had to admit it could not make.

## Stretch

Picked up only if committed work finishes early:

- STORY-051 (M) — CI over both suites. Sprint 4 work, but this sprint closes seven items and
  nothing would catch the eighth.

## Known risks

- **An empty app that says "ingest a document" and offers no way to do it is a dead end.**
  Accepted deliberately: the ingest control is [STORY-043](../../backlog/backlog.md#ready) in
  sprint 5, and the alternative — pulling it forward — was considered and declined at
  planning. The message names `POST /ingest` and a sample filename, so the instruction is
  actionable by anyone with a terminal and nobody else. That is a smaller version of the gap
  this surge exists to close, and it is open for two more sprints.
- **Turning auto-ingest off makes the demo worse before it makes it better.** Anyone who
  runs this expecting sprint 2's 439-document graph will find nothing. The empty states are
  the entire mitigation, which is why they are the sprint's largest item rather than polish.
- **Deleting the unused `Authority`/`Entity` helpers may be premature.**
  [ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md) and the Policy Concierge
  direction in the [vision](../../planning/vision.md) both point at those labels mattering
  later. Deleting tested code a named future needs is not obviously right; leaving
  unreachable code is not either. Whichever way it goes, it belongs in the review with a
  reason.
- **`create_document`'s rollback path is hard to test honestly.** Proving the fix needs a
  failure injected between statements, and a test that mocks the driver to do that would be
  testing the mock. The test has to provoke a real constraint violation mid-transaction.
- **No CI still.** Every check this sprint depends on someone choosing to run it. STORY-051
  is sprint 4 — or this sprint's stretch, if the committed work lands early.
