# Sprint 6 — Plan

**Dates:** 2026-08-26 → 2026-08-26 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

## Sprint goal

**What the pipeline produced becomes visible to the person who ran it, and the checks that claim
the pipeline works become capable of failing.**

Both halves are the same problem seen from two sides. A rebuild of DoDD 5000.01's 2020 edition
wrote 113 obligations on 2026-08-25 and confirming that number required `cypher-shell`; the gate
that certifies extraction quality reported green on every CI run while measuring nothing. In both
cases the system was working and no one inside the product could tell.

## What the planning review found

This plan was written after a seven-lens review — product, backend, UI, QC, requirements, UX and
testing — of the plans, the code and the backlog. The findings that shaped it, each verified
directly rather than taken on report:

1. **The extraction gate had never gated anything.** `FLOORS["null"]` was `{0.0, 0.0, 0.0}`.
   Nothing can score below zero, and because an entry existed the gate's `floors is None` skip
   never fired; the null adapter also bypasses the model-reachability skip, so both "THE
   EXTRACTION GATE DID NOT RUN" messages were disarmed at once. `Settings()` resolves to the null
   adapter, which is what CI runs. ADR-013 claims a provider swap is "a tested property rather
   than a hope"; on every push it was a hope.
2. **The citation invariant was void.** `test_ask.py` asserted
   `any(c["quote"] in body["answer"] or c["quote"] ...)`, which Python binds as
   `(quote in answer) or (quote)` — a non-empty quote satisfies it regardless of the answer. In a
   compliance tool, that is the test standing behind "no claim enters an answer without a passage
   behind it". Repaired; the invariant itself holds.
3. **Triage sent users to a queue that cannot be filled.** Verified live: `from_obligations: 0`,
   `to_obligations: 113`, `total_changes: 113`, `rows: []` — and the screen said "Approve links in
   Review first". A proposal needs obligations on both sides, so Review was unfillable. STORY-067
   closed the `total_changes === 0` case; the one-sided case reached neither branch.
4. **CI has run.** Six green runs since 2026-08-24, including both pushes on 2026-08-26. Sprint
   5's retrospective and this folder's own stub both said it never had.
5. **The roadmap claims a capability with nothing behind it.** `roadmap.md` records that DI-2
   Phase 1 landed `:Authority`/`:Entity` reference nodes. The live graph holds 0 and 0, and
   `merge_authority`, `attach_authority` and `merge_entity` have no production caller — only
   `tests/test_versions.py`. Corrected in this sprint's opening commit.
6. **The three Ready items did not meet the Definition of Ready.** Filed 2026-08-26 by one author
   in one sitting and moved straight to Ready. STORY-082's AC1 recorded only *completed* rebuilds
   while AC5 and AC7 needed in-flight and dead-worker state; STORY-083 carried a criterion no test
   could fail; STORY-081's ordering needed a property the schema does not store. All three
   repaired before commitment, each revision marked in the file.
7. **The estimation scale mispredicted.** Its L row made "crosses backend and frontend"
   *sufficient*, which would have made all three items L. Backend and UI leads independently
   costed them M from the code. [The scale was amended](../../backlog/README.md#estimation) to
   make the crossing a signal rather than a size.
8. **Twenty Done items and seventy-five commits landed after sprint 5 closed** with no sprint, no
   review and no velocity row. Backfilled as an unplanned interval so this sprint sizes against
   real history — see [velocity](../velocity.md).

Findings 1, 2 and 3 were defects, so under [AGENTS.md](../../../AGENTS.md#standing-rules) they
were fixed before this plan was written rather than filed as sprint content. What remains of the
quality work is committed below.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-085 | The ranking weights ADR-025 records are asserted, not just commented | S | — |
| STORY-086 | Route reachability is a test, not a paragraph | S | — |
| STORY-081 | A user can read the obligations extracted from an edition | M | — |
| STORY-082 | A document says whether its derived layer was built, when, and with what | M | — |
| STORY-083 | A graph can be exported before it is destroyed | M | — |
| STORY-084 | The extraction floors are measured against the gold set that exists | S | — |

**Total committed:** 3M + 3S — six items, no L.

Deliberately no L, and the absence is the plan's main safety margin.
[Velocity](../velocity.md) says seven items fit when they are mostly S and that an L displaces
roughly three of them. Sprint 4 and sprint 5 each carried one and each had to argue past the
estimation rule to do it. Six items with no unmade decision inside any of them is the least
heroic slate this project has proposed since the surge began.

## Why this order

**STORY-085 and STORY-086 first.** Both are S, neither depends on anything, and each closes a
gate that cannot currently fail. Doing them first means the rest of the sprint is built on checks
that work. STORY-086 in particular is the corrective action sprint 5's retrospective wrote as
prose and never automated — run by hand at planning, 20 of 20 routes are reachable today and
nothing would notice when that stopped being true.

**STORY-081 next**, because the other two consume it. Its endpoint is where STORY-082's "built,
113 obligations" is displayed, and its obligation serialisation is what STORY-083 exports.

**STORY-082, then STORY-083.** 082 is the connective tissue: three of four live editions show
zero obligations with no way to distinguish never-built from built-with-`null` from died-mid-run.
It also rescues the promise `config.py` now makes — that an overnight rebuild can be read in the
morning — which the product cannot currently keep, because the run id lives only in React state.

**STORY-084 last.** It needs a reachable model, it is the item whose slip costs least, and it is
the one that must not run before the gate it feeds was repaired. This is the role STORY-055
played in sprint 5's plan.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done):

- [ ] **Every acceptance criterion is read back line by line before the item is written into the
      review, and before any story file is deleted.** Sprint 5's retrospective asked for this
      because STORY-057 closed with two of four criteria unmet. The six items here carry 7, 7, 8,
      5, 3 and 5 criteria. This is the sprint where that rule earns its keep.
- [ ] **A browser walkthrough, every step a UI action.** Carried from sprint 5, which established
      that a `curl` walkthrough passes while the claim it stands for stays untrue.
- [ ] **The route-reachability comparison runs as a test.** This replaces sprint 5's final DoD
      bullet — "no client function in `api/client.ts` is left without a caller" — which that
      sprint's own retrospective identified as a check that cannot fail in the way that matters.
      A Definition of Done should not carry a gate the team has already disproved.
- [ ] **The extraction gate is observed to skip loudly or to run.** Not "the suite is green":
      green was the failure mode. If the gate skips, the skip is read and understood.
- [ ] **The Triage one-sided fix is demonstrated against the live state that exists today**, not
      only against a fixture — one edition with 113 obligations, its baseline with none.

## Stretch

None. Sprint 5 refused a stretch list on an eight-item commitment and was right to. If this
session runs long, STORY-084 returns to sprint 7 and the goal still holds — the gate it feeds was
already repaired before the sprint opened.

## Known risks

- **The three M items were sized under a scale amended in the same session that sized them.**
  That is a real conflict of interest, recorded here rather than discovered at review. The
  mitigation is that two reviewers costed them from the code independently and named the specific
  existing shapes each would reuse; if any of the three turns out to be L in practice, the
  amendment is what to re-examine first, not the estimate.
- **The extraction cache can make a "real model" walkthrough vacuous.** A rebuild over unchanged
  content calls the model zero times ([ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)).
  A walkthrough that replays the cache proves the cache, not the model. Plan which edition to
  build before starting: three of four editions in the live graph have chunks and no obligations
  and are therefore genuine cold runs.
- **A cold rebuild costs hours.** ~104 seconds a chunk; the live editions are 38, 41 and 204
  chunks. Do not empty the graph before the walkthrough — its current one-sided state is a free
  fixture for two of this sprint's items, and rebuilding it costs roughly sixteen hours.
- **Velocity is a weak instrument here.** The table now carries a backfilled row for twenty items
  that were never planned or reviewed. It can say this slate is not obviously larger than the last
  one; it cannot say how long any of it takes.
- **Unfiled and known:** `DocumentDetail` polls a running rebuild on a flat 2-second timeout with
  no backoff. At the eight-hour job timeout set on 2026-08-26 that is roughly 14,400 requests per
  open tab per run. Found by the planning review, not yet a story, and not committed here.
