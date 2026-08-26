# Sprint 7 — Plan

**Dates:** 2026-08-26 → 2026-08-26 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

## Sprint goal

**Extraction stops silently losing a fifth of every document, and the loop it feeds is run end
to end on what it produces.**

The second half is the part this project has never done. Sprint 5 produced 265 proposals and
sprint 6 proved the obligations underneath them included section headings. Extraction is now
worth trusting and nothing has been built on it: one edition of one document holds obligations,
Review has never been filled, and **no human has ever recorded a verdict** — which is the one
thing in this system a machine cannot regenerate and the entire reason the product exists.

## Where the product actually is

Measured 2026-08-26, after sprint 6 closed:

| Edition | Built | Obligations |
| --- | --- | --- |
| `dodd-5000-01@2018-08-31` | never | 0 |
| `dodd-5000-01@2020-09-09` | finished | 114 |
| `dodd-5000-01@2022-07-28` | never | 0 |
| `dodm-8180-01@2023-08-04` | never | 0 |

`:LinkDecision` count: **0**. Review is empty and unfillable, because a proposal needs
obligations on both sides of a comparison and only one side has any.

**Two of the three questions sprint 6 carried here are already answered.** Its stub asked what a
`PROMPT_VERSION 1` obligation is worth: nothing is left to decide, because the 2026-08-26 rebuild
dropped all 113 of them and no v1 obligation survives anywhere. It asked what re-extraction would
cost in lost review decisions: zero, because none exist. **That window closes the moment someone
approves a link** — which this sprint intends to do, so the answer is being spent rather than
kept.

The third question is the one below.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| STORY-087 | The blast radius of an unparseable item is decided | S | — |
| STORY-088 | An unparseable item costs what the ADR says it costs | M | — |
| STORY-092 | The Authority and Entity helpers go | S | — |
| STORY-089 | The rebuild status poll backs off | S | — |
| STORY-090 | Review's empty queue names its upstream cause | S | — |
| STORY-091 | The README's corpus numbers describe what the product produces | S | — |

**Total committed:** 1M + 5S — six items, no L.

[Velocity](../velocity.md) says seven items fit when they are mostly S. This is six and five of
them are S. The one M is bounded by a decision taken inside the same sprint, which is the shape
the [estimation guidance](../../backlog/README.md#estimation) prescribes for an L caused by a
missing decision: split the decision out, and the implementation stops being an L.

**The real cost of this sprint is not in the table.** Building a second edition to complete the
loop is roughly an hour of CPU inference, and the Definition of Done below requires it.

## Why this order

**STORY-087 first, and STORY-088 cannot start before it.** The rejection rate is the sprint's
headline problem — 8 chunks in 37 lost whole on 2026-08-26, all `modality: null` on sentences
stating scope — and the fix moves a boundary ADR-023 set deliberately. Sprint 6 tried three
prompt variants against this and none moved it, which is what makes it a decision rather than a
wording problem. A boundary change made before the decision *is* the decision.

**STORY-092 next**, because it is subtraction and gets easier the earlier it happens.

**STORY-089 and STORY-090 next.** Both are single-screen changes, both remove something the UI
currently states misleadingly, and neither blocks anything.

**STORY-091 last, and deliberately so.** It has to be written from the walkthrough's output
rather than before it — its numbers come from the run this sprint's Definition of Done requires,
and writing it earlier would mean measuring the corpus twice.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done):

- [ ] **The loop completes once, end to end, through the UI.** Build a second edition, see real
      proposals in Review, approve one, and see the ranked Triage row it produces. Every step a
      UI action. This has never happened on obligations worth trusting, and until it does the
      product's central claim is untested.
- [ ] **The first `:LinkDecision` in this project's history is recorded by that walkthrough**, and
      survives a subsequent rebuild of one of the two editions — which is what
      [ADR-014](../../specs/adr/ADR-014-proposals-and-decisions-are-different-things.md) and
      [ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) both promise and neither
      has been observed doing with a human verdict behind it.
- [ ] **Every acceptance criterion read back line by line** before the item is written into the
      review, and before any story file is deleted. Carried from sprint 5, kept by sprint 6
      because it caught two things nothing else would have.
- [ ] **The extraction gate runs against a real model, not merely skips.** Sprint 6 left it able
      to do both; a sprint that changes the rejection boundary has to see it run.
- [ ] **The ratchet is re-measured after STORY-088** and its floors updated from the measurement
      if they move, recorded exactly as observed.

## Stretch

None. The two open MVP bars — STORY-036 (XLSX) and STORY-014 (search) — are deliberately not
here. Both are real and neither serves this goal, and the planning rule is to pick the goal first
and then pull what serves it. They are the obvious spine of sprint 8.

## Known risks

- **The rejection fix could make extraction quieter rather than better.** Dropping an item that
  fails validation recovers four fifths of what is currently lost and weakens the property
  ADR-023 leans on: `Modality` is closed so that a model inventing a binding level fails loudly.
  STORY-087 exists to decide that in the open, and STORY-088's criteria require whatever is
  discarded to be counted and reportable. If the ADR concludes the current boundary is right,
  STORY-088 becomes a much smaller change and the sprint still holds — that is a legitimate
  outcome, not a failure.
- **Completing the loop spends a window that is currently free.** Re-extraction costs nothing
  today because no review decision exists. The first approved link changes that, and every later
  extraction change has to carry ADR-027's re-pointing. This is the right trade — a decision
  nobody has ever recorded is a capability nobody has ever tested — but it is a one-way door and
  it is being opened deliberately.
- **An hour of CPU is the sprint's largest single cost**, and sprint 6's rebuild died partway
  through the equivalent. The retry landed in sprint 6, so a transient failure now costs a chunk
  rather than the run; that fix has not yet been exercised against a real transient failure.
- **The graph is a fixture worth keeping.** Its current one-sided state is what STORY-090 needs
  to be demonstrated against. Demonstrate it before building the second edition, because the
  second edition destroys the evidence.
