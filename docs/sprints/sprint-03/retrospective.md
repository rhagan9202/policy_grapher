# Sprint 3 — Retrospective

**Date:** 2026-08-21

*Dated record — written once, not edited afterward.*

## What we're changing

Two changes, both narrow enough to actually happen. A retro that generates ten action items
generates zero.

**1. A survey finding is a hypothesis until something reads the code.** STORY-050 was written
from an AST sweep that listed four symbols with no caller in `src/`, and the story asserted
they were dead. Two greps at implementation time showed one is a heavily used test helper and
three were staged deliberately by a frozen ADR that names their future caller. The sweep was a
fine way to *find* candidates and a bad way to *conclude* anything. From now on, a story whose
evidence is a mechanical scan says so in its notes and states the check that would confirm it —
so the next person knows the finding has not yet been read by a human.

**2. The suite cannot see composition, so the walkthrough is not optional.** For the second
sprint running, the defect that mattered was found by opening the app, not by running tests:
this time a Triage picker rendering empty and unexplained when the corpus has documents but no
editions. Ninety frontend tests missed it because none of them had that shape of corpus. The
cold-start walkthrough stays in the Definition of Done for sprint 4, and it gets one addition —
walk the app in **each** state the data can be in (empty, documents-only, documents with
editions), not just the empty one.

## What went well

- Estimating everything cost about ten minutes and made the overcommit obvious before it
  happened. The one L was removed at planning; the sprint landed 7 of 7 for the first time
  without a stretch being sacrificed.
- Writing ADR-019 immediately after the second rejected proposal caught reasoning that would
  have been unrecoverable a week later. Both rejections were the same underlying move and
  neither had been named as such until they sat side by side.
- Rewriting the plan before any code, rather than quietly working to a plan we knew was wrong.

## What didn't

- **Three of the four "unreachable code" claims in STORY-050 were wrong, and I wrote them.**
  The cost was small because it was caught before deleting anything. It would not have been
  small the other way round: deleting `text_of` would have broken 15 test call sites, and
  deleting the Authority helpers would have contradicted ADR-011 in a way nobody would have
  noticed until the task ADR-011 names came around.
- **My own tests were too loose three separate times** — `getByText` matching several elements
  because the assertion was a bare substring. The component was right each time and the test
  was wrong. Cheap to fix, but it is a pattern now: assertions scoped to a role or a container
  from the start would have avoided all three.
- The frontend has no test for a corpus in the documents-but-no-editions state, which is
  exactly the state the sample CSV produces. There is one now, written after the walkthrough
  found the defect rather than before.
