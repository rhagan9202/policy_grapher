# ADR-034: A statement is a quotation of the passage it was read from

**Status:** Accepted · **Date:** 2026-08-28 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md)**, which put schema validation
in our code on every adapter. This adds a rule to that validation which needs the passage, not
only the item.

## Context

The extraction prompt has required word-for-word quoting since `PROMPT_VERSION = 2`, written in
sprint 6 after the model was found returning statements that began at the verb. The rule is stated
plainly — *"statement must be copied from the passage word for word"* — and it was never checked.

**Measured on the live graph, 2026-08-28: 34 of 196 obligations, 17%, hold a statement that does
not occur in the chunk it was read from.**

| Modality | Obligations | Not a quotation | Share |
| --- | ---: | ---: | ---: |
| SHALL | 92 | 9 | 10% |
| WILL | 38 | 7 | 18% |
| ASSIGNED | 35 | 16 | 46% |
| MUST | 19 | 2 | 11% |
| MAY | 10 | 0 | 0% |
| SHOULD | 2 | 0 | 0% |

The worst case is not a statistic. `PROMPT_VERSION = 3` taught the positional form with a worked
example quoting **USD(A&S)** out of DoDD 5000.01, and the model echoed that example into sections
where it found little to extract. The rebuilt graph recorded USD(A&S)'s duties under
**Paragraph 2.6 (DoD Chief Information Officer)**, **2.7 (Director of Operational Test and
Evaluation)** and **2.10 (CJCS)** — asserting that each of those offices "executes the acquisition
responsibilities in DoDD 5135.02", which the document says of none of them.

**Attributing a duty to the wrong office is the precise failure this product exists to prevent.**

It also breaks identity. `obligation_id` hashes the normalised statement
([ADR-027](ADR-027-a-decision-is-re-pointed-not-orphaned.md)), so a misquotation produces an id
derived from text the document does not contain — and a later extraction that quotes correctly
produces a *different* id, orphaning every human decision recorded against the first. A
misquotation is not a cosmetic error; it is an obligation that cannot be re-found.

This is the third rule in three sprints that the prompt asked for and did not get: the modality
word (sprint 7), the actor that is not a placeholder (below), and this.

## Decision

**A statement must appear, word for word, in the passage it was extracted from. Where the passage
is available, this is checked, and an item that fails is refused.**

1. **Checked in `validate_extracted`**, which both adapters already call — the local adapter when
   the model answers, and the cache when it replays a hit. A rule in only one of them is a rule a
   cache hit steps around.
2. **Normalised on both sides, exactly as `obligation_id` normalises** — case-folded, whitespace
   collapsed. A chunk holds the document's line breaks and a statement is one line; a raw
   comparison would refuse every real obligation.
3. **Evidence-based, not assumed.** The check runs only when the caller supplies the passage.
   Absent it there is no evidence, and declining to reach a verdict is better than inventing one.
4. **A refusal costs the item, not the chunk** ([ADR-030](ADR-030-a-rejected-item-costs-itself-not-its-chunk.md)),
   reported through the existing drop channel.
5. **It applies to every modality**, not only to `ASSIGNED` where the echo was found. The rule was
   always general; only the enforcement is new, and SHALL is misquoted 10% of the time.

## Consequences

**It costs nothing measurable.** Measured three times at temperature 0 with the guard as the only
change: precision 0.905, recall 0.889, modality 1.000 — **identical, to six decimal places, to the
same measurement without it.** All eighteen gold obligations are quotations of their chunks, so
the gate cannot tell the guard is there. That is the argument for it: it is free on correct
answers and fatal to echoes.

**It will drop obligations on the next rebuild of existing editions**, roughly one in six by the
measurement above, and it should. Those are misquotations, and this product quotes policy.

**It does not catch a partial echo.** A model that copied a *prefix* of the example, or one whose
echo happened to appear in the passage, still gets through. The guard is exact rather than
heuristic for the same reason ADR-033's actor rule is: a similarity threshold would refuse real
duties to catch these.

**A prompt fix was tried and rejected, and the rejection is the interesting part.** Replacing the
worked example with a fictional office removed the echo's source — and made the model stop
recognising the positional form altogether, labelling every item `SHALL` and taking that fixture
from five of five to zero. Measured, not guessed. **A concrete example is what teaches the form;
the guard is what makes echoing it harmless.** They are not alternatives, and treating them as
alternatives cost a measurement cycle.

## Alternatives considered

**Fix the prompt only.** Tried, measured, rejected — see above. It also leaves the general 17%
untouched, since most misquotations have nothing to do with the worked example.

**Refuse only `ASSIGNED`.** Where the echo was found, and where the rate is worst. Rejected because
SHALL is misquoted 10% of the time and the rule the prompt states was never modality-specific.
Scoping the enforcement narrower than the rule would leave the same defect in the majority
category.

**A similarity threshold rather than exact containment.** Would catch near-misses the exact rule
lets through. Rejected: it converts a deterministic check into a tuned one, and the threshold would
have to be defended against the same gold set that cannot currently see any difference.
