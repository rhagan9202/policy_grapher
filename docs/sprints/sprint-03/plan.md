# Sprint 3 — Plan

**Dates:** 2026-08-21 → 2026-08-21 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

First sprint in the [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge), and the
first in this project's history where every committed item carries an estimate. The
[t-shirt scale](../../backlog/README.md#estimation) and the
[cadence](../README.md#cadence) were both decided at this planning session, closing three
standing `TODO:` markers that sprints 1 and 2 each carried forward.

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

From a wiped volume, `docker compose up` reaches a state where Triage, Review and Ask hold
real data through product actions alone — and every "has landed" claim in the planning
documents is true of the running app rather than of its library.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| [STORY-048](../../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) | An ingested edition's derived layer can be built from the running app | L | — |
| STORY-049 | A cold start produces a corpus with text in it | M | — |
| STORY-050 | The codebase contains no code the application cannot reach | S | — |
| STORY-038 | Creating a document through the API is one transaction | S | — |
| STORY-053 | Planning documents describe the running app, not its library | S | — |

**Total committed:** 1L + 1M + 3S. Sprints 1 and 2 delivered 13 and 7 stories, so five is
deliberately below the observed rate — the L carries an unmade decision, and
[the estimation note](../../backlog/README.md#estimation) says an L in a sprint is a warning
rather than a plan.

**STORY-053 is committed last on purpose.** It rewrites the claims in `roadmap.md` and
`architecture.md` to match reality, and reality is what the four items above it change. Doing
it first would document a state that no longer holds by the end of the session.

## Why this order

**STORY-048 first, because everything else in the surge assumes it.** The audit that produced
this backlog could only exercise Triage, Review and Ask by running Python against the
container's Neo4j. Until a product action can do that, sprint 4 cannot verify its defect fixes
against real screens and sprint 5 has nothing to build UI against.

**STORY-050 rides with 048 rather than after it.** Wiring `CachedExtractor` and
`GraphCacheStore` into the rebuild path is part of 048's acceptance criteria; what is left of
050 is the genuinely dead code — `attach_authority`, `merge_authority`, `merge_entity`,
`text_of` — which is a deletion decision, not a wiring one.

**STORY-038 is here because it is a known silent-corruption bug, not because it is related.**
It has sat in Refining since sprint 2's review deferred it, `architecture.md` lists it first
under *Known weak points*, and it blocks STORY-044 in sprint 5. A surge whose goal is "combed
for bugs" should not step over the one bug already written down.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done), one addition
specific to this goal, because it is the thing the suite cannot check:

- [ ] **A cold-start walkthrough is performed and recorded in the review**:
      `docker compose down -v && docker compose up -d --build`, then the documented product
      actions, then screenshots of Triage and Review holding real rows. Not a test run — an
      observation, of the kind sprint 2's review had to admit it could not make

## Stretch

Picked up only if committed work finishes early:

- STORY-041 (S) — the missing favicon. Sprint 4 work, but it is a one-file fix and the only
  console error the audit found.

## Known risks

- **STORY-048 contains an unmade decision, and it is not a small one.** Synchronous route,
  background task, or CLI: with a real model, extraction is one call per chunk over 38 chunks,
  so a synchronous route is wrong the moment the extractor is not `null` — and the `null`
  default makes that invisible in every test. If the decision takes the session, the honest
  outcome is an ADR and no implementation, and the sprint misses its goal. **Mitigation:**
  make the decision first, in writing, before any code; treat "ADR written, route deferred"
  as a legitimate result rather than a failure to be hidden.
- **The green suite is the hazard, not the safety net.** 509 backend tests pass against a
  product whose three newest screens cannot be filled. Every unit here is correct in
  isolation and nothing composes them, so no test in the suite can fail on the defect this
  sprint exists to fix. Only the cold-start walkthrough above can.
- **`source_uri` is a container path.** `rebuild_derived` re-reads the PDF from
  `file:///data/samples/...`, which resolves inside the backend container and nowhere else.
  Fine while the caller is the backend; a trap for anything that moves later.
- **STORY-049 may argue with ADR-012.** Making a cold start useful probably means auto-ingest
  seeding a PDF edition rather than only the CSV manifest, which changes startup from a fast
  structural operation into one that chunks and possibly extracts. If that coupling is
  unacceptable, the answer is a documented one-command path instead — and the story is then
  smaller than M.
- **Deleting the unused `Authority`/`Entity` helpers may be premature.**
  [ADR-007](../../specs/adr/ADR-007-sources-describe-documents.md) and the Policy Concierge
  direction in the [vision](../../planning/vision.md) both point at those labels mattering
  later. Deleting tested code that a named future needs is not obviously right; leaving
  unreachable code is not either. Whichever way it goes, it belongs in the review with a
  reason.
- **No CI still.** Every check this sprint depends on someone choosing to run it. STORY-051
  is sprint 4, which means sprint 3 closes the largest gap in the project with the weakest
  guard it will ever have.
