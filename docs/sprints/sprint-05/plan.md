# Sprint 5 — Plan

**Dates:** 2026-08-23 → 2026-08-23 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

Third and last sprint in the [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge).

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

No backend capability is left without a way to reach it from the UI — the corpus-management
bar in [What success looks like](../../planning/vision.md#what-success-looks-like) is met.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-059 | The stack coming up is proved by a check, not by a person | S | — |
| STORY-060 | No decision is enforced against a default the deployment overrides | S | — |
| STORY-044 | A user can create, delete and cross-reference documents from the UI | L | — |
| STORY-043 | A user can ingest a document from the UI | M | — |
| STORY-017 | A user can review the extracted text and metadata of any ingested document | M | — |
| STORY-042 | A reviewer can work through the whole queue, not just its head | M | — |
| STORY-046 | A user can empty the graph from the UI | S | — |
| STORY-055 | Extraction recognises the modality this corpus actually uses | M | — |

**Total committed:** 1L + 4M + 3S — eight items.

**This is the largest commitment in the project's history and it is a deliberate overcommit.**
The evidence against it is worth writing down at planning time rather than discovering at review.
[Velocity](../velocity.md) says seven items fit when they are mostly S, and that an L displaces
roughly three of them; sprint 4 committed 1L + 2M + 1S and that filled the session *before* its
walkthrough found two defects that had to be fixed inside the sprint. This slate is roughly ten
item-equivalents against sprint 4's six. The [estimation
note](../../backlog/README.md#estimation) also says an L in a sprint is a warning rather than a
plan.

Two things make it less reckless than the arithmetic suggests, and neither makes it safe.
STORY-044's L is breadth, not an unmade decision — its one dependency, STORY-038, landed in
sprint 3, so the five client functions it needs are built, tested and merely unreachable. And
five of the eight items are UI work over an API that already exists, which is the cheapest shape
of work this project has. **The project owner committed this slate with the capacity evidence in
front of them.** If it does not land, the review says so, and the [sequencing
below](#why-this-order) says which item is expected to be the one that slips.

## Why this order

**STORY-059 and STORY-060 first, because they are cheap and they protect everything after
them.** 059 puts `docker compose build` behind CI, which matters more than its S suggests:
sprint 4 changed the backend image, both `uv sync` stages, and the build arguments for two
services, and the only thing that ever proved any of it was a person running one command.
060 sweeps the remaining `Settings` fields for the gap that let every container ask Ollama for a
model [ADR-020](../../specs/adr/ADR-020-model-weights-come-from-us-organisations.md) forbids. It
goes early because the knowledge is fresh — a sweep run three sprints from now is run by someone
reconstructing why it matters.

**STORY-044 next, and early rather than late, which is the sprint-4 lesson applied.** It is the
spine of the goal: `createDocument`, `deleteDocument`, `getDocument`, `addReference` and
`removeReference` are five of the nine client functions the 2026-08-21 audit found unreachable,
and no other item closes them. Sprint 4 gave its L the session's best hours and the L landed;
putting the largest item last is how a sprint discovers at hour six that it cannot finish.

**Then the four remaining UI items, 043 first.** `POST /ingest` has existed since DI-1 and
nothing calls it, so loading the corpus is a `curl` command — which means the person this tool is
for cannot put a document into it. It also makes every later screen demonstrable without a
terminal, so it pays for itself across the rest of the sprint. 017, 042 and 046 are independent
of each other and of 043; 046 is an S carrying a destructive action, so it needs a confirmation
step and a plain statement of what it deletes — including that it does *not* clear the vector
index.

**STORY-055 last, deliberately, because it is the item whose slip costs least.** The
[roadmap](../../planning/roadmap.md#the-tech-debt-surge) put it in sprint 6; sprint 4's
[retrospective](../sprint-04/retrospective.md) asked for it here, on the grounds that there are
finally real numbers to argue from — 241 obligations extracted across two editions, against
`will` outnumbering `shall` 458 to 93 in the samples. Both are right, and the tie-breaker is
that it is the only committed item that does not serve the sprint goal. **If this sprint
overruns, STORY-055 is what goes back**, and it goes back to sprint 6 where the roadmap already
had it. Nothing else in this list can slip without failing the goal.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done), carrying forward the
walkthrough with the leg sprint 4's retrospective asked for:

- [ ] **A walkthrough covering each state the data can be in** — empty, documents-only,
      documents with editions, and a derived layer built through the product.
- [ ] **At least one rebuild against the real extractor**, not the `null` default. New this
      sprint, and the reason it exists: every walkthrough before sprint 4's closing one
      satisfied its derived-layer bullet with `EXTRACTOR_ADAPTER=null`, which writes chunks and
      no obligations — so the half of the pipeline that needs a model stayed unwalked for three
      sprints and then failed twice within twenty minutes of first being tried.
- [ ] **Every walkthrough step is a UI action.** The sprint's whole point is that the API is
      reachable without a terminal. A walkthrough driven by `curl` would pass while the thing
      being claimed remained untrue — the same shape of false green as a CI that skips its
      integration half.
- [ ] **No client function in `api/client.ts` is left without a caller**, except `runQuery`,
      which [ADR-008](../../specs/adr/ADR-008-authenticated-non-cypher-audience.md) parks on
      purpose.

## Stretch

Nothing. An eight-item commitment that also carries a stretch list is not a plan, and naming one
here would suggest the committed slate has slack it does not have.

## Known risks

- **The commitment is roughly ten item-equivalents against a session that has delivered six.**
  Stated above and repeated here because it is the dominant risk and no mitigation removes it —
  only the sequencing limits the damage, by putting the droppable item last.
- **STORY-044 is an L with three distinct flows inside it** — create, delete, and
  cross-reference. It is committed whole. If it is going to be split, the split should happen
  when the first flow lands, not after the third has run out of session: `addReference` and
  `removeReference` are the natural seam, and cross-referencing is the half a reviewer can live
  without for one more sprint.
- **STORY-046 exposes a destructive route to a button.** `POST /reset` empties the graph and
  does *not* clear the vector index — `ensure_vector_index` rebuilds it on the next embed
  precisely because [ADR-016](../../specs/adr/ADR-016-embeddings-are-a-port.md) treats a
  reset-orphaned index as the failure it is. A confirmation dialog that describes this wrongly
  is worse than no dialog.
- **STORY-055 reopens a closed enum and needs a superseding ADR before any code.** `Modality`
  is closed on purpose — `extraction/schema.py` says a downgrade from SHALL to SHOULD is silent
  and therefore unacceptable — and widening it changes what every recorded obligation means,
  including the 241 already extracted. It also needs its own ratchet leg, and
  [ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md) names it as the
  first thing to consider next. This is the second sprint running with an item whose decision
  must be written before its code.
- **The frontend suite cannot see composition, and this is a frontend sprint.** Three
  consecutive sprints have had their real defect found by opening the app rather than by running
  the suite — 90 frontend tests missed a Triage picker rendering empty, and 550 backend tests
  missed a container asking for a forbidden model. A sprint that is almost entirely UI work is
  the worst possible one in which to trust a green suite.
- **CI has never actually run.** `.github/workflows/ci.yml` was written and verified command by
  command in sprint 4, but no run of it has executed — the push carrying it was rejected for
  want of `workflow` scope on the OAuth token. The first push of this sprint is still the
  experiment, and STORY-059 adds a job to a workflow nobody has watched succeed.
