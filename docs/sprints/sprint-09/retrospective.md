# Sprint 9 — Retrospective

**Date:** 2026-08-28

*Dated record — written at sprint close, not edited afterward.*

## What we're changing

**1. A test that measures a system must be given what the system needs to run.** The extraction
gate failed at recall 0.61 and the floor was right to fire — but the extractor had not regressed.
`test_the_configured_extractor_clears_its_floors` called `extract()` without `section_title`, so
ADR-033's guard refused every ASSIGNED obligation in the gold set for want of a title the gate
never passed. **It was measuring the guard rejecting its own fixtures, and reporting that as the
model's score.**

This is a new failure shape for this project and worth naming. Sprints 6, 7 and 8 each produced a
test that *passed* when it should have failed. This one *failed* when it should have passed, and
the danger is the opposite: the obvious response to a red floor is to lower it, and lowering it
here would have recorded a fabricated regression permanently.

The rule: **when a gate goes red after an interface changed, check that the gate is calling the
new interface before believing what it says about the thing behind it.** The cheap diagnostic is
to run the same input by hand — which is what identified this in one command.

**2. A guard's letter can be satisfied while its purpose is defeated, and only real documents show
it.** ADR-033 requires an ASSIGNED obligation to name an actor. The model, unable to find a role
heading, copied the whole statement into `actor`. Non-null, passes, names nobody.

No fixture could have caught this: the gold set is what a *correct* answer looks like, so it holds
no such item. **This is the fourth sprint running in which the defect that mattered was found by
running the product rather than by the suite** — and the second in which the failure was a model
obeying a rule's wording to avoid its intent.

The rule: **when a guard requires a field to be present, ask what the cheapest way to satisfy it
is, and assume a model will find that way.** Presence checks invite filler.

## What went well

- **No floor was lowered at any point**, in a sprint whose plan named a lowered floor as the way
  this gate would die, and whose first measurement was red. Both measured legs rose: precision
  0.833 to 0.842, recall 0.769 to 0.889, identical on three consecutive runs.
- **Mutation caught a vacuous test before it shipped.** STORY-099's first version asserted that no
  route answers 404, passed on its first run, and — this is the part that matters — still passed
  with sprint 8's defect deliberately reintroduced. The mutation step this project adopted as a
  standing action is what turned that from a green tick into a real check.
- **Running the parse over the corpus found what reasoning about it did not.** Two of the sprint's
  defects — a third heading format, and the references skip that never fired — were invisible in
  unit tests and obvious the moment the code was pointed at `data/samples`. Both were found before
  the expensive rebuild, not after.
- **Splitting the decision from the implementation paid a third time.** ADR-033 was written the
  day before the sprint and the implementation had an answer for every question that arose,
  including the one the ADR got wrong.
- **The ADR being wrong was cheap.** ADR-033 said the guard reads `section_path`; it cannot, since
  the chunker discarded section titles. Because the decision — *guard by the section* — was
  recorded separately from the mechanism, the mechanism could be corrected in the spec without
  reopening anything.

## What didn't

- **I wrote a plan step that assumed a fact I had not checked.** The plan called for storing
  `section_title` on `:Chunk` because `rebuild_derived` "reads chunks back". It does not — it calls
  `chunk_pages()` directly. Caught while implementing, and the storage was dropped rather than
  built unused, but a plan is supposed to spare the implementer that discovery.
- **I repeated ADR-030's original mistake.** Skips were first routed through the rejection channel,
  so a clean rebuild reported a references section as a rejection. The ADR that exists precisely to
  separate "refused" from "not offered" is one I had read that morning.
- **I reverted a whole task's work while trying to undo a one-line mutation.** `git checkout` on
  the file under test discarded the implementation along with the mutation. Recovered by
  re-applying, and no work was lost, but the mutation step needs a backup copy rather than a
  revert — which is how the later mutations in this sprint were done.
- **The headline number is not verified.** 31 ASSIGNED obligations against a hand count of 21. The
  offices match, so it is not wholesale invention, but nobody has read the 31 against the document
  and the review says so rather than quoting the number as coverage.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Verify the 31 recovered duties against the document before the number is quoted as coverage | — | Sprint 10 |
| Decide what an actor *is* (STORY-100) — the field became load-bearing the moment duties were defined by the office they fall on | — | Sprint 10 |
| When a gate goes red after an interface changed, check the gate calls the new interface before believing it | — | Standing |
| When a guard requires a field, assume a model will find the cheapest way to fill it | — | Standing |
| Mutate by keeping a copy of the file, never by reverting it | — | Standing |

## Follow-up on last sprint's actions

**"Assert that every declared route is exercised by at least one real request."** Done as
STORY-099, and the first version of it did not work. Asserting "no route answers 404" passed with
sprint 8's exact defect reintroduced, because a shadowed route still answers — from the wrong
handler. The test now asserts which route matched.

**"When a new test passes on its first run, mutate the thing it guards before believing it."**
Held, and it is the reason the action above reads as it does. Every new test in this sprint was
mutated; one was found vacuous, and five guards were confirmed to fail when their rule was removed.
