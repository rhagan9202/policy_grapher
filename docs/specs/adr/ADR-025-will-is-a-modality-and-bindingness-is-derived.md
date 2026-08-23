# ADR-025: WILL is a modality, and bindingness is derived

**Status:** Accepted · **Date:** 2026-08-23 · **Deciders:** —
**Amends:** [ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md)

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

`Modality` was closed to `SHALL | MUST | SHOULD | MAY`, and `extraction/schema.py`
explained why in a sentence worth keeping: *"SHALL misread as SHOULD downgrades a binding duty
to advice, silently — so an adapter that invents a value must fail loudly."* That reasoning is
correct and this ADR does not weaken it.

The problem was never the closure. It was the contents. Counted across the seven sample PDFs,
**`will` appears 458 times against `shall` 93** — and the split is generational rather than
incidental:

| Edition | `shall` | `must` | `will` |
| --- | --- | --- | --- |
| DoDD 5000.01 (2003) | 92 | 0 | — |
| DoDD 5000.01 (2020 re-issue) | **0** | — | 44 |

DoD's plain-language drafting replaced the directive `shall` with `will`. On five of the seven
samples, an extractor obeying the old set could only report a minority of the document's duties
— and on the 2020 re-issue, structurally none of them. [ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md)
recorded this as a known limitation and named widening the set as the first thing to consider
next.

Two facts made this cheap to get right. `obligation_id` hashes `version_id`, `section_path` and
the normalised statement — **not modality** — so widening the set does not change any
obligation's identity and therefore does not orphan a single recorded decision
([ADR-014](ADR-014-proposals-and-decisions-are-different-things.md)). And the corpus has been
extracted exactly once, in sprint 4's walkthrough, into a development database.

## Decision

**`WILL` joins the set, and bindingness becomes a derived property rather than something each
consumer works out.**

1. **`Modality` gains `WILL` and stays closed.** The member records *the word the passage used*,
   not its force. The prompt is explicit that WILL is a duty and not a prediction, and that an
   extractor must not silently reclassify it as SHALL — the word is evidence about the document
   and throwing it away loses the ability to tell a 2003 edition from its 2020 re-issue.
2. **`ExtractedObligation.is_binding` answers the question consumers actually have.** `SHALL`,
   `MUST` and `WILL` bind; `SHOULD` and `MAY` do not. Derived, not extracted: asking a model to
   judge bindingness would make the answer vary by model, when it is a reading this project
   makes once and records here.
3. **`MODALITY_WEIGHT["WILL"] = 4.0`, equal to SHALL.** Anything lower would rank the 2020
   re-issue of an issuance as less urgent than its 2003 edition purely because the drafting
   convention changed underneath it.
4. **The ratchet gains a will-dense gold fixture** — six WILL duties and not one SHALL, from the
   2020 re-issue, labelled by reading the passage. Before this change the correct answer to that
   passage was *structurally unreachable*: every duty in it used a word the schema rejected.

## Consequences

**Makes easy.** Extraction can now report the majority of a modern DoD issuance's duties.
Everything downstream that asks `is_binding` keeps working when the set changes again, because
the set is stated in one place.

**Makes hard.** Five modalities is more surface for a model to get wrong, and `will` is
genuinely ambiguous in English — "the system will fail" is a prediction, not a duty. The prompt
addresses it in words; nothing measures it yet beyond one fixture. Expect the first real
false-positive class to be predictive `will` read as directive.

**A consumer keeping its own list is now the failure mode**, and this project already had one:
`MODALITY_WEIGHT` in `changes/propagate.py`. It was caught immediately, by
`test_every_modality_the_schema_allows_has_a_weight`, which asserts the weight table's keys
equal the enum's members — a guard written for exactly this moment by someone who anticipated
it. That test is the reason this ADR could add a member without silently mis-ranking every WILL
obligation in Triage. `is_binding` exists so the next such list does not have to be found by
hand.

**Assumption:** the floors are not re-measured here. `test_extraction_ratchet`'s precision and
recall were observed against `llama3.1:8b` over three fixtures and six gold obligations, and its
own note says they *"pass by zero margin"* and that *"widening the gold set is the prerequisite
for treating this as a real gate"*. This adds a fourth fixture and six more gold obligations,
which improves that. **It does not re-measure the floors against the widened enum**, so the gate
is currently measuring a model that was never asked for WILL against floors set before WILL
existed. That is a known gap, deliberately not closed in a sprint already carrying eight items,
and it is the first thing to do when the ratchet is next run.

## Alternatives considered

**Normalise `will` → `SHALL` at extraction.** Rejected. It keeps the set at four by asserting an
equivalence the corpus never states, and permanently destroys the evidence distinguishing a 2003
edition from its re-issue. It is also the same *shape* of move as the silent downgrade the
closed set exists to prevent — a word replaced by another word, on the extractor's authority,
where nothing downstream can see it happened.

**Add `WILL` and nothing else.** Rejected, narrowly, and it was the tempting option. Every
consumer reasoning about bindingness would have to learn that WILL counts, and *today none of
them do* — so each becomes a silent under-count until someone remembers to update it. The
`MODALITY_WEIGHT` table proved the point within a minute of the enum changing.
