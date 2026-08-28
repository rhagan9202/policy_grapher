# Sprint 10 — Review

**Dates:** 2026-08-28 · **Goal:** what the graph says about who must do what is true, and checked

*Dated record — written at sprint close, not edited afterward.*

> **Correction, 2026-08-28 (sprint 11 planning): the hand count of 21 in this document is wrong.** DoDD 5000.01 (2020) contains **40** lettered items under role headings in its responsibilities section. The 21 came from the coarse regular expression this project used throughout sprints 9 and 10, which misses gerund items and cannot tell which role heading an item sits under. Actual coverage was 19 of 40. See the [sprint 11 plan](../sprint-11/plan.md).

## The goal, measured

**Met.** Every acceptance criterion of the rebuild passes against the live graph:

| Check | Result |
| --- | --- |
| Obligations whose statement is not a quotation of the chunk it is anchored in | **0** of 157 |
| `ASSIGNED` duties recorded under paragraphs 2.6, 2.7 or 2.10 | **0** |
| Obligations with a placeholder actor | **0** |
| `:LinkDecision` surviving the rebuild | **1**, with its `IMPLEMENTS` edge intact |

The graph no longer claims that the DoD Chief Information Officer, the Director of Operational Test
and Evaluation and the Chairman of the Joint Chiefs of Staff each execute USD(A&S)'s acquisition
responsibilities. It did before this sprint, in eight obligations.

**The graph is smaller, on purpose.**

| Edition | Before | After |
| --- | ---: | ---: |
| DoDD 5000.01 (2003) | 93 | 83 |
| DoDD 5000.01 (2020) | 76 | 56 |
| DoDD 5143.01 | 15 | 13 |
| **Total** | **184** | **152** |

Thirty-two obligations, 17%, were removed because they misquoted their passage, named a party the
statement did not, or attributed a duty to an office the document did not name. The sprint plan
said the review should be comfortable reporting a large number, and this is it.

`ASSIGNED` fell from 31 to 26 across the graph, and on DoDD 5000.01 (2020) specifically from 31 to
19 against a hand count of 21 — from half again too many to slightly under, with the offices now
matching the six the document names.

## Committed items

| ID | Item | Size | Outcome |
| --- | --- | --- | --- |
| STORY-101 | Every edition is rebuilt under the rules the extractor now has | M | Delivered. Two passes, five acceptance checks |
| STORY-100 | An office is one actor, not several spellings | L | Decided as [ADR-035](../../specs/adr/ADR-035-an-actor-is-validated-before-it-is-canonicalised.md), and the decision is not the one the story expected |
| STORY-102 | A prompt rule nobody checks is not a rule | L | Decided as [ADR-036](../../specs/adr/ADR-036-a-checkable-prompt-rule-is-checked.md), with the registry and its tests |

## What STORY-100 turned out to be

The story asked whether actor fragmentation was one problem or two. Reading all 80 distinct values
answered a different question: **the field was not holding office names.** Alongside real offices
and real classes of party it held abstract nouns that bear no duty (`Competition`,
`Advanced technology`, `DoD Issuances`), a conditional clause
(`When using performance-based strategies`), a pronoun, the string `the passage`, and the
truncation artefacts `gers` and `e systems`.

**So ADR-035 decided validity before identity**, and deferred normalisation and `:Entity` — not
because they are hard, but because canonicalising an 11%-invalid field produces confident junk.
`gers` would have become a durable node with an id, which is worse than a messy string because it
looks authoritative.

The measurable rule — a word-modality actor must occur in its statement — removed the invalid ones.
Distinct actors fell from 81 over 171 obligations to **71 over 123**. That is not canonicalisation
and the review should not be read as claiming it: the remaining 71 still contain both `USD(A&S)`
and `The USD(A&S)`, which is exactly what STORY-100 was filed about and exactly what ADR-035
declines to fix yet.

**One of the fourteen removed obligations is worth recording permanently.** Its statement was
`"WILL is a duty here, not a prediction."` and its actor was `"the passage"`. That sentence is from
the extraction prompt. The model returned an obligation extracted from its own instructions, and it
stood in the graph until this sprint.

## What STORY-102 produced

`PROMPT_RULES` registers all 14 rules the prompt states — 8 bound to a validator, 6 carrying a
written reason no validator can exist — and `test_prompt_rules.py` asserts the registry and the
prompt have not drifted apart. Three mutations confirm it: rewording a prompt rule fails, adding a
rule with neither validator nor reason fails, naming a validator that does not exist fails.

**It proves a link, not a correctness.** A wrong validator passes. ADR-036 says so, because a
registry believed to mean more than it does would rebuild the same false confidence one level up.

Enumerating the rules found something reading the prompt had not, across four sprints of reading
it: **two places where the prompt contradicts itself**, both introduced by ADR-033. A statement
must include the subject that carries the duty — an `ASSIGNED` statement begins at the verb. An
actor is copied from the statement — an `ASSIGNED` actor comes from the heading above it. Filed as
[STORY-103](../../backlog/stories/STORY-103-the-prompt-stops-contradicting-itself.md) and
deliberately not fixed in-sprint: correcting the prompt bumps `PROMPT_VERSION`, which discards the
extraction cache, and three rebuilds were in flight.

## A defect found by refusing to accept a number

DoDD 5143.01's rebuild reported 190 items dropped against 17 written — a ratio unlike the other two
editions. The investigation did not find a problem with the document. It found that the run
reported **20 reasons against 213 refusals**, and that nothing told a reader the list had been
capped.

`REPORTED_REJECTIONS = 20` is right, and its comment already said why: enough to see the shape of a
failure without letting a pathological run write an unbounded blob into Redis. What was missing is
that the cap was invisible — the counts were honest and the list silently was not, which is the
shape [ADR-030](../../specs/adr/ADR-030-a-rejected-item-costs-itself-not-its-chunk.md) made a
silent drop into a defect.

Fixed: `rejections_total` counts every refusal, uncapped, beside the capped list. It also exposed a
smaller bug — `save_meta()` was called only when an entry was appended, so once the cap was reached
the metadata stopped being written to Redis, where the status route reads it.

## What is not claimed

**The invariant is verified once, not continuously.** "No stored obligation misquotes its chunk" was
checked against the live graph and passes at 0 of 157. It is not a CI test, and deliberately so: the
integration harness builds a fresh graph with a stub extractor whose statements are quotations by
construction, so such a test would pass without guarding anything — the vacuous-test failure this
project has hit in three separate sprints. The invariant is enforced at write time by
`validate_extracted`, which is mutation-tested.

**Two editions were never built and still are not.** DoDD 5000.01's Change 1 edition and
DoDM 8180.01 have source files and no obligations. Building them is new coverage rather than
correcting false data, and DoDM 8180.01 alone is 204 chunks — several hours. Out of scope for a
sprint about truth, and named here so the corpus figures are not misread.

**The rebuild took two passes because of a sequencing mistake**, not because two were needed.
ADR-035's actor rule landed after the first pass had started, so the graph had to be rebuilt again
to reflect it. The second pass was cheap — cache entries replay through `validate_extracted`, so
the new rule applied without re-running the model — but the rework was avoidable by ordering the
rule changes before the long-running job.

## Definition of Done

- **Acceptance criteria met** — read back against the code and, for STORY-101, against the graph.
- **Tests written and passing** — 372 unit tests, integration suite green, extraction gate green.
- **Every new guard mutated before being believed** — the actor rule, the registry's three links,
  and the rejection total.
- **Documentation updated in the same change** — two ADRs, this review, the backlog.
- **Runs under `docker compose up` from a clean checkout** — every rebuild reported here was driven
  through the running application.
