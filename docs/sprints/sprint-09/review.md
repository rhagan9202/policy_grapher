# Sprint 9 — Review

**Dates:** 2026-08-28 · **Goal:** the product can see the duties DoD actually writes

*Dated record — written at sprint close, not edited afterward.*

> **Correction, 2026-08-28 (sprint 11 planning): the hand count of 21 in this document is wrong.** DoDD 5000.01 (2020) contains **40** lettered items under role headings in its responsibilities section. The 21 came from the coarse regular expression this project used throughout sprints 9 and 10, which misses gerund items and cannot tell which role heading an item sits under. Actual coverage was 19 of 40. See the [sprint 11 plan](../sprint-11/plan.md).

## The goal, measured

**Met.** DoDD 5000.01's 2020 edition now yields **31 obligations assigned by position**, where
the product previously saw none — not because it read them badly, but because `Modality` had no
member that could express what the document does. The edition went from **56 obligations to 76**,
a 36% gain, and the part gained is the section a compliance reader asks for first.

The offices those duties fall on are the ones the document names:

| Actor | Duties |
| --- | ---: |
| USD(A&S) | 12 (plus 2 recorded as "The USD(A&S)" — see below) |
| USD(R&E) | 5 |
| Director of Cost Assessment and Program Evaluation | 4 |
| USD(I&S) | 4 |
| DoD Component heads (the full enumerated phrase) | 1 |
| USD(P&R) | 1 |
| "acquisition executive" | 2 |

## Committed items

All four delivered.

| ID | Item | Size | Outcome |
| --- | --- | --- | --- |
| STORY-097 | The responsibilities section is invisible | M | Delivered. ADR-033 implemented across schema, guard, prompt and gold set |
| STORY-098 | Front matter is not offered to the extractor | M | Delivered. 51 of 580 chunks corpus-wide, ~76 minutes of inference per full rebuild |
| STORY-099 | Every declared route is reached by a real request | S | Delivered, after the first version of the test was found to guard nothing |
| STORY-075 | A chunk on a section join reports the right page | S | Delivered. Boundary bug, not a leading-newline bug, decided by a test that distinguishes them |

## The extraction floors

Measured three times at temperature 0 on the shipped code, identical on every run:

| | Floor before | Measured | Floor now |
| --- | ---: | ---: | ---: |
| precision | 0.833 | **0.905** | 0.842 |
| recall | 0.769 | **0.889** | 0.888 |
| modality accuracy | 0.85 | **1.000** | 0.85 (held) |

**No floor moved down at any point**, which this sprint's plan named as the way this gate would
die. Recall gains most and the gain is the sprint itself: five duties that no member of `Modality`
could express are now expressible, and the model returns all five with the right actor on each —
the new gold fixture scores recall 1.000.

**Getting the floors right took two attempts, and both failures are recorded in the file.** The
first recorded recall as 0.889 against a measured 0.888888..., and the gate failed on itself: the
comparison is `measured < floor`, so a floor rounded *up* sits above the number it came from.
Every floor in this file's history is a truncation for that reason, which had never been said out
loud.

**Precision is floored at 0.842 rather than the observed 0.905, and that is a finding rather than
caution.** The same gold set measured 0.842 in a separate process earlier the same day, on the
build immediately before the actor rule: 19 predictions of which 16 matched, against 21 of which
19 matched afterwards. **Recall was 0.889 in both — the same sixteen gold obligations were found
either way** — so what moved is how many predictions the model emitted, not what it understood.
Three runs inside one process have been identical every time this project has measured them; two
processes are not, and nothing in the file had ever said so. A floor at 0.905 would fire on that
variation, and a floor that fires on something nobody changed teaches people to ignore it.

`modality_accuracy` was not raised to the observed 1.000, following the reasoning already recorded
beside it: over sixteen matched pairs a single error reads as 0.938, and a floor that fires on one
differing answer teaches people to ignore it. 0.85 still tolerates one and catches two.

**The permissive-MAY fixture still scores recall 0.000**, as it has since sprint 7. The model
produces nothing valid for it, ADR-030 makes that a rejected chunk, and it is priced into the
recall floor rather than hidden. 0.889 is what this adapter scores *including* one fixture it has
never read.

## Five defects found while executing, all fixed in-sprint

**1. The route test guarded nothing on its first write.** It asserted that no declared route
answers 404 to a real request. It passed — and it still passed with sprint 8's defect
deliberately reintroduced, `/{slug}` declared above `/duplicates`. The reason is worth keeping: a
shadowed route still answers, from the wrong handler, which returns 404 only because no document
is named "duplicates" and 500 under a stubbed driver. **A status code cannot distinguish a working
route from a shadowed one.** The test now also asserts which route matched, using Starlette's own
matcher, and fails naming `GET /documents/duplicates -> /documents/{slug}`.

**2. A third heading format existed and was invisible.** DoDD 5143.01 numbers its top-level parts
and writes the title inline — `3.  RESPONSIBILITIES AND FUNCTIONS.  The USD(I&S) is...`. Neither
the named-heading form nor the title-on-the-next-line form finds it, so that document resolved
**zero** section titles and ADR-033's guard would have refused every positional duty in it. Found
by running the parse over `data/samples` rather than reasoning about it. Corpus coverage went from
72 to 90 chunks in a responsibilities section.

**3. The references half of STORY-098's skip never fired.** Checking `section_title` alone skipped
**zero** references sections across the entire corpus, because the older format opens `REFERENCES`
as a bare heading — which becomes a `section_path` element and leaves no title line to parse.
Checking both places took the skip from 27 chunks to 51 of 580, and from ~40 to ~76 minutes of
inference saved per full-corpus rebuild.

**4. Skips were routed through the rejection channel — ADR-030's original mistake, repeated.**
Two integration tests caught it: a clean rebuild reported a references section as a *rejection*,
and a run with one bad chunk reported seven. A skip is not a rejection; nothing was refused and
nothing is missing from the edition.

**5. The extraction gate did not pass the section title it now depends on.** This is the one worth
reading twice. The first ratchet run after ADR-033 landed **failed at recall 0.61 against a floor
of 0.769** — and the floor was right to fire. But the extractor had not regressed:
`test_the_configured_extractor_clears_its_floors` called `extract()` with the chunk text and
section path only, so ADR-033's guard refused every ASSIGNED obligation in the gold set for want
of a title the gate never passed. **The gate was measuring the guard rejecting its own fixtures.**
Extracting the same fixture by hand with the title supplied returned all five, which is what
identified the harness rather than the model.

## The defect the rebuild found, which no fixture could have

The first real rebuild under ADR-033 returned 33 ASSIGNED obligations. **Two of them had `actor`
set to the whole statement, character for character.**

The model could not find a role heading and satisfied "ASSIGNED requires an actor" by copying the
sentence into the field. That passes a non-null check while naming nobody — it obeys the guard's
letter to defeat its purpose, which is precisely the exposure ADR-033 accepted when it admitted a
value that names no word and must therefore be guarded structurally.

Fixed with an exact rule rather than a length heuristic: an ASSIGNED obligation's normalised actor
may not equal its normalised statement. The alternative shape — "the actor must be shorter than
the statement" — would have refused a real duty from the same rebuild, whose actor is the
150-character phrase "DoD Component heads, including the Directors of the Defense Agencies with
acquisition authority but not the CJCS...". **A model that copied a prefix rather than the whole
sentence would still get through. That is a stated limit, not an oversight.**

After the fix and a re-run: 31 ASSIGNED, and zero with an actor equal to its statement.

**No fixture would have found this.** The gold set is what a correct answer looks like, so it
contains no such item. This is the fourth sprint running in which the defect that mattered was
found by running the product rather than by the suite.

## What is not settled, and should not be quoted as if it were

**31 against a hand count of 21.** The plan named 21 positional duties counted by hand in this
edition, and the rebuild produced 31. The offices match the six the document names, so this is not
wholesale invention — the excess is most likely additional duty-bearing sentences *inside* lettered
items, which the hand count did not count separately. **It is unverified.** Until someone reads
the 31 against the document, "31 duties recovered" is a measurement of what the extractor emitted,
not of what the section contains.

**Actor is free text and is not canonical.** The same office appears as `USD(A&S)` (12) and
`The USD(A&S)` (2), and one actor is the fragment `acquisition executive`. Nothing in the code
claims actors are canonical, so this is a limitation rather than a defect — but it directly
affects the Policy Concierge direction, which wants to ask "what is this office responsible for".
Filed as STORY-100.

**A quarter of positionally-shaped items are still refused by design.** Measured while writing the
spec: 151 such items sit in a section titled RESPONSIBILITIES and 49 elsewhere, chiefly PROCEDURES
in DoDI 8500.01. ADR-033's guard refuses all 49. That is a deliberate first cut, precision over
recall, and widening it is a new decision rather than a quiet edit.

## Two deviations from the plan

**`section_title` is not stored on `:Chunk`.** The plan called for it. `rebuild_derived` calls
`chunk_pages()` directly and never reads chunks back out of the graph, so nothing would have read
the stored property — the shape STORY-092 deleted `:Authority` and `:Entity` for. If Ask or
retrieval later wants it, storing it becomes a change with a caller.

**An ASSIGNED statement stays verbatim, with the office in `actor`.** The plan's prompt draft had
the model compose "The USD(A&S) executes …" from the heading and the item. `obligation_id` hashes
the normalised statement, so a composed subject varies with whatever wording the model picks and
silently detaches the reviews recorded against that clause. The subject is not lost; it is in the
field that exists for it.

## Definition of Done

- **Acceptance criteria met** — read back one at a time against the code, not the tests.
- **Tests written and passing** — 358 unit tests and the integration suite, both green.
- **Every new test mutated before being believed** — and one was found vacuous by doing it.
- **Reviewed and merged** — see the branch history; every commit records what it decided and why.
- **Documentation updated in the same change** — this review, the backlog, ADR-033's consequences.
- **Runs under `docker compose up` from a clean checkout** — the rebuild reported here was driven
  through the running application, not by calling Python by hand.
