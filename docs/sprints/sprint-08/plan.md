# Sprint 8 — Plan

**Dates:** 2026-08-27 → 2026-08-27 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

## Sprint goal

**The product meets its own definition of done, and the definition is checked rather than
attested.**

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

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-036 | Ingestion accepts an XLSX manifest | M | — |
| STORY-093 | The vision says which of its bars cannot be started | S | — |
| STORY-014 | A user can search for a document by name or ID from anywhere in the UI | M | — |
| STORY-094 | The MVP's definition of done is checked, not attested | M | — |

**Total committed:** 3M + 1S — four items, no L.

**Four is deliberate, and smaller than the last two sprints.** The MVP is nearly met, so the
sprint that closes it is small by arithmetic rather than by caution. The cost that is not in the
table is in the Definition of Done below: restoring the corpus and building a second *instrument*
is roughly an hour of inference, and it is the first time anything here is demonstrated across
more than one document.

STORY-036 is sized **M** against the **S** sprint 6's backend review gave it. That review costed
the parser and the dispatch correctly and did not account for the fixture, which has to be
generated from the sample CSV, committed, and kept faithful to it.

## Why this order

**STORY-036 first.** It is the one bar that closes by writing code, it has no dependency on
anything else here, and STORY-094 asserts its result — writing the assertion first would mean
asserting a bar that has not shipped.

**STORY-093 next**, because it is one document telling the truth about itself and takes minutes.

**STORY-014 third.** The decision it needed was taken at planning and is recorded in the story: a
search control in the header that submits to the existing Documents table with its filter
applied, rather than a new results screen. That reuses the table, its cap-and-say-so behaviour
and its row rendering, and adds one control and one predicate.

**STORY-094 last**, so it asserts the state the sprint actually leaves behind rather than the one
it hoped for.

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

None. If the session runs long, STORY-094 returns to the backlog and the sprint still closes
three of the four bars — but the goal's second clause fails, and that should be recorded as a
miss rather than smoothed over.

## Known risks

- **STORY-094 could grow into an L if "checked" is read expansively.** A test for "handles a
  corpus of 20 documents" could mean a count, or a full ingest-render-browse exercise. The story
  scopes it to bars that are cheap to check against a running graph and requires the rest to be
  recorded as unchecked with a reason. If that scoping is abandoned mid-sprint the item is an L
  and displaces roughly three others.
- **The rejection rate is untouched and still the largest quality question open.** Twenty of
  thirty-seven chunks yield nothing, and sprint 7's retrospective assigned the diagnosis here.
  It is deliberately excluded because it does not serve this goal, and that decision costs a
  third sprint of the product's honest output being roughly half what it extracts. The ratchet is
  ready to answer it whenever it is picked up.
- **A manifest ingest creates `:External` nodes in bulk**, and the corpus assertion has to not be
  fooled by them. The bar says documents; the graph mostly holds references. That distinction is
  written into STORY-094's criteria because getting it wrong would produce exactly the false
  green this sprint exists to prevent.
- **Building a second instrument costs an hour and can fail.** Sprint 7's transient-failure retry
  has never been exercised against a real transient failure, and sprint 6's rebuild died on one.
