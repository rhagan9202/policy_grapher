# Sprint 10 — Plan

**Dates:** 2026-08-28 → TBD · **Capacity:** one working session

*Dated record — written at sprint start, not edited afterward.*

## Goal

**What the graph says about who must do what is true, and checked.**

Sprint 9 made the product able to read duties assigned by position. Verifying its own headline
number found that the graph was asserting things the documents do not say — USD(A&S)'s duties
recorded under three other offices — and that this was the visible corner of a general problem:
**17% of every obligation in the graph holds a statement that is not in the passage it was read
from.**

The rules that prevent it are now enforced. This sprint makes the *existing* graph obey them, and
addresses the reason such rules kept going unenforced for a sprint at a time.

## Why this goal, and why the two obvious alternatives are dead

Both alternatives sprint 9's stub named were investigated before this session, and both were
closed by evidence rather than judgement.

**Scale cannot be tested, and the blocker is not capacity.** The graph holds 460 documents, of
which **3 have an edition and 437 are cited names with no file behind them**. There are **7 source
files** in `data/samples`. The manifest's 438 rows are *references*, not documents to ingest.
"Prove it at scale" is not a sprint goal until somebody supplies PDFs, and saying so is more useful
than planning around a number that describes a bibliography.

**Widening ADR-033's guard is not worth what it looked like.** Sprint 9's spec measured that ~25%
of positionally-shaped items sit outside a responsibilities section and are refused. Reading them
shows the measurement was counting the wrong things: the largest group, `PROCEDURES` in DoDI
8500.01, is dominated by items that **already carry a modal verb** — "Organizations will implement
processes and procedures…", "DoD will establish and maintain a continuous monitoring capability" —
and by lettered *headings* ("Standards-Based Approach.") and statements of fact ("Enclaves always
assume the highest security category"). The guard is refusing far less real content than the
number implied. **Leave it, and correct the spec's figure in the review.**

## Committed

Three items: 1L + 2M. The L is a decision, and the sprint is sized small because the M items each
end in a rebuild.

| ID | Item | Size | Why it is here |
| --- | --- | --- | --- |
| [STORY-101](../../backlog/stories/STORY-101-the-graph-is-rebuilt-under-the-rules-it-now-has.md) | Every edition is rebuilt under the rules the extractor now has | M | The guards fix what is written next and touch nothing already there. Five editions, and an acceptance test that no stored obligation misquotes its chunk |
| [STORY-100](../../backlog/stories/STORY-100-an-office-is-one-actor-not-several-spellings.md) | An office is one actor, not several spellings | L | The decision the Policy Concierge direction waits on. Now with numbers to argue from |
| [STORY-102](../../backlog/stories/STORY-102-a-prompt-rule-nobody-checks-is-not-a-rule.md) | A prompt rule nobody checks is not a rule | L | Three sprints, three unenforced prompt rules, each found in the data. This is the one that stops a fourth |

**That is 1M + 2L against a scale that says an L displaces about three items.** Deliberately
overcommitted in decision-work and undercommitted in code: both L items are expected to produce an
ADR and little else, which is the shape sprint 8 delivered two of successfully. If one slips, it is
STORY-102 — it is the least urgent and the most likely to grow.

## What STORY-100 now knows that it did not

The story was filed asking whether actor fragmentation is one problem or two. Measured on the live
graph, 2026-08-28: **81 distinct actors across 171 obligations with an actor.** It is at least
four problems, and a decision that treats them as one will be wrong about three of them:

| Kind | Evidence |
| --- | --- |
| Article and case variants | Folding case, articles and whitespace merges only **10 of 81** |
| Number and abbreviation variants | `pm` (7) and `pms` (9) are the same office |
| Not an office at all | `acquisition managers`, `dod components`, `dod` — generic noun phrases |
| Not a name at all | **7 actors longer than 60 characters**; one is a whole sentence's worth of enumerated offices |
| Placeholders | **20 obligations carried the string `"null"`** — fixed 2026-08-28, listed because it was part of the same count |

The cheapest option in the story — normalise on the way in — addresses the first row and none of
the others. That is the argument the ADR has to answer.

## Definition of Done

The project's [standing gates](../../backlog/README.md#definition-of-done) apply unchanged, plus
the two sprint 9 added to the read-back: acceptance criteria read against the code rather than the
tests, and every new test mutated before it is believed.

One gate specific to this sprint: **the rebuild's acceptance test is a query over stored data, not
a test of the extractor.** Sprint 9 proved the extractor obeys the rule. This sprint has to prove
the graph does.

## Risks

**A rebuild that drops 17% of obligations is the largest test ADR-027 has faced.** Decisions are
re-pointed by statement, and this rebuild deliberately changes which statements exist. If a
`:LinkDecision` is stranded, that is the finding, and it is more important than the counts.

**STORY-102 could become a prompt rewrite.** The middle option — generating prompt text from the
validators — is the strongest guarantee and the largest change, and it would touch the file whose
last two edits each moved every extraction number. The ADR should say plainly what it costs before
anyone writes code.

**Nothing here improves what the product can read.** Three sprints have widened coverage; this one
narrows it, on purpose. The review should say how many obligations were removed and be
comfortable that the number is large.
