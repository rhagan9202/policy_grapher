# Sprint 6 — Review

**Date:** 2026-08-26 · **Participants:** —

*Dated record. Written once, at the end of the sprint.*

## The goal

> What the pipeline produced becomes visible to the person who ran it, and the checks that
> claim the pipeline works become capable of failing.

**Met, and the two halves turned out to be the same finding.** The checks were made capable of
failing first; the first thing they caught was that the pipeline's central output was wrong.

## Committed and delivered

| ID | Item | Est. | Delivered |
| --- | --- | --- | --- |
| STORY-085 | The ranking weights ADR-025 records are asserted | S | Yes |
| STORY-086 | Route reachability is a test, not a paragraph | S | Yes |
| STORY-081 | A user can read the obligations extracted from an edition | M | Yes |
| STORY-082 | A document says whether its derived layer was built, when, and with what | M | Yes |
| STORY-083 | A graph can be exported before it is destroyed | M | Yes |
| STORY-084 | The extraction floors are measured against the gold set that exists | S | Yes, at L |

**Six of six.** Every acceptance criterion was read back line by line against what shipped
before this file was written, which is the carried action sprint 5's retrospective assigned
here — and it changed two entries below.

## What the sprint found

**The headline gate had never gated anything.** `FLOORS["null"]` was `{0.0, 0.0, 0.0}`. No score
falls below zero, and because an entry existed the gate's `floors is None` skip never fired; the
null adapter also bypasses the model-reachability skip. Both "THE EXTRACTION GATE DID NOT RUN"
messages — written precisely so a green suite could not be mistaken for a passing gate — were
disarmed at once, and `Settings()` resolves to the null adapter, which is what CI runs. ADR-013
claims a provider swap is "a tested property rather than a hope". It was a hope.

**Un-disarming it produced a red gate, and the red was real.** Measured against the widened gold
set with a live llama3.1:8b:

    precision 0.294   recall 0.385   matched 5 of 13     against floors of 0.60 / 0.50

It looked like a scoring artefact and was not. The model wrote statements beginning at the verb,
moving the subject into `actor`: "PMs shall manage programs consistent with statute" came back as
"manage programs consistent with statute". `scoring.py` matches on the same normalised form
`obligation_id` is hashed from — deliberately, because a statement that does not quote the
passage produces an id that orphans the review decisions recorded against the old one.

**Live data agreed, and STORY-081 is what made it visible.** The obligations screen shipped and
immediately showed what the 2026-08-25 rebuild had actually written: "Employ Artificial
Intelligence, Machine Learning, Deep Learning...", "Implement Effective Life-Cycle Management",
"Emphasize Environment, Safety, and Occupational Health" — section headings, extracted as
obligations, each carrying the literal string "no actor specified" where null belongs. The
product had been building on that since extraction first ran.

**Fixed by fixing the extractor, which is what the ratchet demands.** PROMPT_VERSION 2 says what
v1 left implicit: quote the whole sentence including its subject and closing full stop; the
modality you report must be a word that appears in the sentence you quote; null is the value for
a missing actor. It names the three shapes that look like duties and carry no modal verb — scope
statements, headings, and bare lettered task lists — because all three were being reported.

    before   precision 0.294   recall 0.385   matched  5 of 13
    after    precision 0.625   recall 0.769   matched 10 of 13
    floors   0.60              0.50

Three passes, each measured. Quoting the subject moved `shall_dense` from 0 matched to 3;
requiring the closing full stop and the modal word to appear in the quoted sentence moved
`mixed_modality` from 0 to 2. Identical on three consecutive runs at temperature 0, before and
after. Floors recorded exactly as observed, as this file has always done.

## Three defects fixed before the sprint opened

Found by the planning review, and under [AGENTS.md](../../../AGENTS.md#standing-rules) fixed
rather than committed as sprint content:

- `FLOORS["null"]`, above.
- `test_ask.py` asserted `any(c["quote"] in body["answer"] or c["quote"] ...)`, which Python
  binds as `(quote in answer) or (quote)` — a non-empty quote satisfies it regardless of the
  answer. In a compliance tool that is the test standing behind "no claim enters an answer
  without a passage behind it". The invariant itself holds; the test was proving nothing.
- Triage told a user to "Approve links in Review first" when `from_obligations` was 0, so no
  proposal could exist and Review could never be filled. STORY-067 closed the `total_changes ===
  0` case; the one-sided case reached neither branch.

## What the work caught while it ran

- **STORY-086's reachability test caught STORY-081's own route**, within an hour of existing:
  "the browser cannot reach 1 route(s) the server declares". Exactly the defect class it was
  built for.
- **Two of STORY-081's route tests passed vacuously when first written.** Asserting only
  `status_code == 404` succeeds while the route does not exist at all. They now assert the
  route's own detail message names the missing slug or edition.
- **An intermittent frontend failure, about one run in eight**, traced to `mockReset` dropping a
  mock's implementation and leaving a window where a React passive effect that had not flushed
  called a bare `vi.fn()` and threw on `undefined`. Cleared rather than reset now; 15 consecutive
  clean runs.
- **A case only live data showed.** The build record begins now, so the edition holding 113
  obligations from an earlier rebuild would have read "never built" directly above a list of its
  own obligations. Obligations are what separate the two readings of a missing record.

## Definition of done

- [x] **Every acceptance criterion read back line by line.** Done before this file was written.
      It is what caught that STORY-081's AC6 could not be met until STORY-082 landed — recorded
      in the commit rather than claimed — and that STORY-084's AC3 had never actually been seen
      to fire, which was then verified by mutation.
- [x] **A browser walkthrough, every step a UI action.** Driven against the running stack:
      Graph, Documents, Ingest, Triage, Review, Ask, Reset, and a document's own page. The
      rebuild was queued by clicking *Build derived layer*, not by `curl`. No console errors, no
      HTTP ≥ 400 on any screen.
- [x] **The route-reachability comparison runs as a test.** STORY-086, and it replaced sprint
      5's final DoD bullet, which that sprint's own retrospective had disproved.
- [x] **The extraction gate observed to skip loudly and to run.** Both: it skips with the
      message under the default `null` configuration, and passes against a live model.
- [x] **The Triage one-sided fix demonstrated against the live state.** Verified in the browser
      against `from_obligations: 0, to_obligations: 113, total_changes: 113`.

## Numbers

- **295 backend unit, 343 backend integration, 183 frontend** — 821 tests, from 610 at sprint
  start. CI green on every push.
- **Extraction cost is unchanged.** 91 s a chunk measured across this sprint's rebuild against
  104 s recorded in sprint 5, so the longer v2 prompt costs nothing in wall clock — worth
  recording because sprint 5's retrospective made "record what a change costs" a standing rule,
  and the honest answer here is "nothing".

## The rebuild, end to end

Queued from the UI and run against a live model after everything above had landed. The first
attempt died at chunk 24 of 37 on a single 500 from a model server that recovered seconds later
— which is how the retry gap was found and fixed, and which STORY-082 recorded durably rather
than losing with the tab. The retry replayed the cached chunks and finished.

    PROMPT_VERSION 1     113 obligations    2 of 37 chunks rejected
    PROMPT_VERSION 2     120 obligations    8 of 37 chunks rejected

More obligations, from fewer surviving chunks — and the difference is what they are:

    section headings recorded as obligations   5+  ->  0
    actors reading "no actor specified"        many ->  0

Statements now carry their subjects, which is what makes an `obligation_id` stable against the
passage it was read from: "Approved program baseline parameters will serve as control
objectives", where v1 wrote fragments beginning at the verb.

**The rejection rate is the cost, and it is not small.** One chunk in five is now lost whole to
`modality: null` on sentences that state scope rather than duty, against one in eighteen before.
Three prompt variants were tried against it — rewording the rule, removing the quoted negative
example, generalising the negatives — and none moved it, so this is a real trade for the
precision gain rather than a wording problem. It is the first question in
[sprint 7's stub](../sprint-07/plan.md).
