# Sprint 8 — Plan

**Dates:** 2026-08-27 → 2026-08-27 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

## Sprint goal

**The product meets its own definition of done, the definition is checked rather than attested,
and the questions this project has been carrying get answered.**

The goal was widened at planning, after the slate was. The first two clauses were the original
sprint; the third covers six items pulled in from Refining and from sprint 7's retrospective —
every deferred item except the one that cannot be started. A goal that half the committed work
did not serve would be worse than an honest one that is broad.

The second clause is doing real work. The [vision](../../planning/vision.md#what-success-looks-like)
lists the MVP bars in prose and nothing verifies any of them, so a bar is met according to
whoever last read the list. That is how the corpus bar stopped being met without anyone noticing
— see below. This project has spent two sprints turning claims into gates; the definition of done
is the last big claim in that shape, and it is the one every other claim is judged against.

## Where the product actually is

Measured 2026-08-27, after sprint 7 closed:

| MVP bar | Status |
| --- | --- |
| Corpus of 20 documents | **Not met — 2.** 50 `:Document` nodes, 48 of them `:External` |
| Ingests from the file system | Met |
| Processes PDF, DOCX, XLSX, CSV | PDF and CSV met. **XLSX open** (STORY-036). **DOCX blocked** |
| Docker, pinned Neo4j | Met |
| Graph to a configurable render cap | Met |
| Corpus management, review of text and metadata | Met, and widened by STORY-081 |
| API calls return correct payloads | Met — 654 tests |
| Search by name or ID | **Not met** (STORY-014) |

**The corpus bar regressed silently.** Sprints 6 and 7 rebuilt the graph around two editions of
one directive, and nothing said the corpus had fallen to two documents. Every number those
sprints reported — extraction quality, 112 proposals, a ranked Triage row — was measured against
**one document**, and that was never stated because nothing was counting. STORY-094 exists so it
cannot happen quietly again.

**DOCX is genuinely blocked, and differently from XLSX.** No `.docx` exists in this repository,
verified again at planning. PDF extraction was built against seven real DoD issuances and is
ratcheted against a corpus CSV describing them; a DOCX path designed against a file we invented
would be fitted to our own guess and the ratchet could not tell us it was wrong. XLSX sits in the
same sentence of the same bar and is *not* blocked, because a manifest is our own format.
STORY-093 makes that distinction visible where the bar is stated.

## Committed

**The MVP bars — the sprint as originally planned:**

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-036 | Ingestion accepts an XLSX manifest | M | — |
| STORY-093 | The vision says which of its bars cannot be started | S | — |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | M | — |
| STORY-094 | The MVP's definition of done is checked, not attested | M | — |

**The carried questions — pulled in at planning:**

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-095 | The rejection rate is diagnosed | M | — |
| STORY-096 | How a reissue's edits are recognised is decided | S | — |
| STORY-047 | A reissued document's edits are recognised as edits, not wholesale replacement | M | — |
| STORY-076 | A rebuild says how many rejections a re-key stranded | S | — |
| STORY-073 | Each edition is ratcheted against its own reference set | L | — |
| STORY-031 | Near-duplicate documents can be reconciled | L | — |

**Total committed:** 2L + 5M + 3S — ten items.

**This is by a wide margin the largest commitment in this project's history, and it is a
deliberate overcommit.** The evidence against it belongs at planning rather than at review.

[Velocity](../velocity.md) says seven items fit when they are mostly S, and that an L displaces
roughly three of them. On that reading this slate is worth about sixteen item-equivalents against
a session that has delivered six twice running. Sprint 5 was the previous record at roughly ten,
and its plan called that an overcommit; this is half again as large. The
[estimation note](../../backlog/README.md#estimation) also says an L in a sprint is a warning
rather than a plan, and there are two.

**What the two L items have in common is why they are L**: each contains a decision nobody has
taken. STORY-073 needs to decide where a per-edition reference set lives; STORY-031 needs to
decide what merging two documents means for the graph. Both keep the decision as their first
acceptance criterion rather than being split, because in each the decision is local — it changes
a fixture's shape or one screen's behaviour, and nothing else reads it. STORY-047's decision was
split out as STORY-096 because that one supersedes an ADR, which is a different weight of thing.

**What would make this hold, if it holds:** four of the ten are S or decision items that produce
a document rather than a feature, three are contained changes to code whose shape is already
known, and STORY-095 is a spike whose output is an answer rather than an implementation. What
would make it fail is either L turning out to need its decision *and* its implementation in the
same session, which is exactly what splitting is supposed to prevent and what keeping them
unsplit risks.

## Why this order

**The MVP bars first, in their original order** — STORY-036, then STORY-093, then STORY-014, then
STORY-094 — because they are the sprint's original goal, they are the ones with a deadline in the
sense that anything else does, and STORY-094 has to assert the state the others leave behind.

**Then the decisions, before the code that depends on them.** STORY-096 (the reissue pairing ADR)
before STORY-047, which is unstartable without it. STORY-073 and STORY-031 each begin with their
own decision as the first acceptance criterion, and if either decision proves larger than it
looks, **stop there and let the item be the decision** — that outcome is a success, not a
shortfall, and it is what splitting would have produced anyway.

**STORY-076 wherever it fits.** It is small, it depends on nothing here, and it is newly testable:
until 2026-08-27 no `:LinkDecision` existed at all, so a stranded rejection could not be observed.

**STORY-095 last, and expect it to slip.** It is a spike, its slowest part is pulling a second
model's weights, and it is the item whose deferral costs least because it has already been
deferred twice without the sky falling. Putting it last is not a judgement about its value — it is
the highest-value quality question open — but about what a session can absorb.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done):

- [ ] **The corpus is restored to at least 20 documents** by ingesting the sample manifest
      through the UI, and the count is of documents that are not `:External` — 48 of the 50 nodes
      present at planning were external references, and counting nodes would report the bar met
      when it is not.
- [ ] **A second instrument is built, not a second edition of the first.** Every measurement this
      project has ever reported comes from DoDD 5000.01. One more document with a derived layer
      is what makes "it works" a claim about the product rather than about one file.
- [ ] **Every acceptance criterion read back line by line** before the item is written into the
      review. Third sprint running, and it has caught something in each.
- [ ] **A browser walkthrough, every step a UI action**, covering search from a screen that is
      not Documents.
- [ ] **The extraction gate runs against a real model at least once**, since a sprint that
      ingests a new document and builds it has no excuse not to.

## Stretch

None, and on this slate the word would be meaningless.

**What matters instead is what gets dropped first if the session runs short**, decided now rather
than in the moment: STORY-031, then STORY-073, then STORY-095. The two L items go first because
an L that half-lands leaves a decision taken and an implementation unfinished, which is the worst
state to stop in. STORY-095 goes third because its value survives waiting.

**The four MVP bars are the last things to drop.** If they do, the sprint fails its original goal
and that gets recorded as a failure rather than reframed.

## Known risks

- **STORY-094 could grow into an L if "checked" is read expansively.** A test for "handles a
  corpus of 20 documents" could mean a count, or a full ingest-render-browse exercise. The story
  scopes it to bars that are cheap to check against a running graph and requires the rest to be
  recorded as unchecked with a reason. If that scoping is abandoned mid-sprint the item is an L
  and displaces roughly three others.
- **The overcommit is the risk, and it is not a small one.** Roughly sixteen item-equivalents
  against a session that has twice delivered six. The mitigation is the drop order above, decided
  in advance, and the fact that four of the ten produce a document rather than a feature. The
  failure mode to watch for is the one this project has seen: an item declared done because its
  headline behaviour works while two of its acceptance criteria are unmet. Reading the criteria
  back line by line is in the Definition of Done for the third sprint running, and on ten items
  it matters more than it has yet.
- **Two L items, neither split.** The backlog's guidance is to split an L caused by a missing
  decision. These are kept whole because their decisions are local — a fixture's shape, one
  screen's behaviour — where STORY-047's superseded an ADR and was split. If either turns out to
  need an ADR after all, the item becomes its decision and the implementation moves to sprint 9.
- **A manifest ingest creates `:External` nodes in bulk**, and the corpus assertion has to not be
  fooled by them. The bar says documents; the graph mostly holds references. That distinction is
  written into STORY-094's criteria because getting it wrong would produce exactly the false
  green this sprint exists to prevent.
- **Building a second instrument costs an hour and can fail.** Sprint 7's transient-failure retry
  has never been exercised against a real transient failure, and sprint 6's rebuild died on one.
