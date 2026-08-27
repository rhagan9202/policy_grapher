# Sprint 8 — Retrospective

**Date:** 2026-08-27 · **Participants:** —

*Dated record. Never edited — the value is in what the team believed at the time.*

## What we're changing

**1. A check that never calls the thing it checks is a check on the declaration, not the system.**
`GET /documents/duplicates` answered 404 for the whole sprint and every test passed. The frontend
mocks the client, so its tests never reach the server. STORY-086's reachability check — written
one sprint ago, precisely to stop capabilities shipping unreachable — compares the routers'
declared paths against `client.ts` and **calls neither**. It was correct for its own purpose and
blind to this.

The fix is not a better reachability check. It is that **at least one test per route must make a
real request to it.** The route tests already do this for most routes; the two added this sprint
did not, and nothing noticed the difference. That is checkable — a test can assert every declared
path appears in some test's request — and it is the natural next step for the file STORY-086
created.

**2. When a sprint runs long, the acceptance criteria read-back is the thing to protect.** It was
the last gate before this review and it found two unmet criteria — a search control asserted
against a hardcoded list rather than the navigation declaration, and a route criterion covered
only at the parser. Both were items I had already called done. Ten items in, at the end of the
longest session this project has run, is exactly when that step feels least necessary and is most
likely to catch something.

## What went well

- **The overcommit held, and the plan said in advance why it might.** Four of ten produced a
  document rather than a feature, and the two L items were L because of decisions answerable from
  evidence already gathered. Recording that reasoning at planning made the outcome readable
  instead of lucky — the same thing sprint 5's plan did.
- **Splitting a decision from its implementation worked a second time.** STORY-096 wrote ADR-031
  and STORY-047 implemented it, and the implementation had an answer for every question that came
  up, including what a false pairing costs. The two L items kept their decisions inside
  themselves and both were answerable in-session, which is the outcome that justifies not
  splitting when the decision is local.
- **The tests taught me what the system does, three times.** The render cap trims externals only,
  because corpus documents always survive. Merges cannot be keyed on slugs, because ADR-005
  reassigns them. A cache entry can predate a validation rule and still fail on replay. None of
  those came from reading code; all three came from a test failing for a reason I had not
  predicted.
- **The MVP is met.** Every bar closed or recorded as blocked, and the definition now fails a
  build when it stops being true.

## What didn't

- **Two of my own acceptance criteria were satisfied in letter and not in substance**, and I had
  moved on from both. STORY-014's asked for the navigation declaration and got a hardcoded list;
  STORY-036's named a route and got a parser test. Both would have passed a review that read the
  tests rather than the criteria.
- **A vacuous test nearly shipped again.** STORY-047's first ambiguity test used two candidates
  scoring *identically*, which is blocked by the comparison alone — it passed with the margin set
  to zero, so it tested nothing the margin does. This is the third sprint running in which a test
  written to guard something new turned out not to guard it, and in each case the tell was the
  same: **it passed the first time it was run.**
- **The rejection-rate finding is bigger than the sprint that found it.** The product cannot see
  the responsibilities section of a DoD issuance — the part that assigns duties to organisations —
  because DoD writes it without modal verbs. That has been true since extraction shipped, it was
  invisible until the schema got strict enough to refuse it out loud, and it is now the largest
  open question about whether this product does what it says.

## Actions

| Action | Owner | By |
| --- | --- | --- |
| Assert that every declared route is exercised by at least one real request, in `test_routers.py` | — | Sprint 9 |
| Decide what a duty written without a modal verb is (STORY-097) — the decision is the work, and it is an ADR before it is code | — | Sprint 9 |
| When a new test passes on its first run, mutate the thing it guards before believing it | — | Standing |

## Follow-up on last sprint's actions

**"Decide whether a 54% chunk-rejection rate is the model, the prompt, or the chunker."** Done as
STORY-095, and the answer was none of the three as posed: roughly half of every document states
no duty at all, and the part that does state duties without modal verbs is a fourth explanation
nobody had listed.

**"When verifying that a class of thing is gone, assert the property, never a list of examples."**
Held. STORY-073's coverage guard asserts `RATCHETS` names every PDF in `data/samples` rather than
listing the ones it knows about, and STORY-094's file-type check compares against the vision's
list rather than a hardcoded set.

**"Before a schema or validation change, query what the graph and the extraction cache already
hold under the old rules."** Held, and it paid: STORY-095's first measurement used cache presence
and would have reported 7 rejected chunks instead of 21, because a cached payload can predate a
rule and still fail on replay.
