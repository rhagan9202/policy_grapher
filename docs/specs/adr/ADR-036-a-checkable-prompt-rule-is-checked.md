# ADR-036: A checkable prompt rule is checked, and the link is asserted

**Status:** Accepted · **Date:** 2026-08-28 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

Decides [STORY-102](../../backlog/stories/STORY-102-a-prompt-rule-nobody-checks-is-not-a-rule.md).

## Context

Four rules, four sprints, one shape:

| Rule, as the prompt states it | Written | Found | Extent when found |
| --- | --- | --- | --- |
| The modality word must appear in the statement | v2, sprint 6 | Sprint 7 | 18 of 215 obligations were headings labelled `SHALL` |
| The statement is copied word for word | v2, sprint 6 | Sprint 9 | 34 of 196, 17%, were not quotations |
| Never write a placeholder actor — use null | v2, sprint 6 | Sprint 9 | 20 obligations carried the string `"null"` |
| The actor is copied from the statement | v2, sprint 6 | Sprint 10 | 14 of 123 word-modality actors were not in it |

Every one was written in the same sprint. Every one went unenforced for at least one sprint after.
Every one was found by looking at extracted data rather than by a test. **Every one was then fixed
deterministically in `schema.py` in under an hour**, because each was checkable all along.

The fourth was found because sprint 9's retrospective predicted a fourth would exist. That is the
argument for a mechanism rather than a fifth fix.

**The cause is structural, not carelessness.** A prompt is a string. Nothing executes it, nothing
imports it, and no test relates its sentences to the validators in `schema.py`. A rule that is
merely written reads exactly like a rule that holds — to a reader, to a reviewer, and to the person
who wrote it a sprint earlier.

Enumerating the current prompt: **19 distinct rules.** Seven were enforced before this sprint (the
closed modality enum, the modality word, non-null modality, the confidence range, ADR-033's actor
requirement, ADR-033's section guard, and the nullable-field contract). Three more were enforced
during it. **At least two remain checkable and unchecked** — that a statement ends with its closing
full stop (5 of 184 violate it), and that a statement does not begin with its enumerator (1 of
184). The rest need judgement: *"do not infer a duty that is not written"* cannot be validated
deterministically, and pretending otherwise would be worse than admitting it.

Enumerating also exposed **two places where the prompt contradicts itself**, both introduced by
ADR-033 and neither noticed until the rules were listed side by side:

- *"statement must be copied ... as a complete sentence including the subject that carries the
  duty"* against ADR-033's instruction that an `ASSIGNED` statement is the lettered item, which
  begins at the verb and has no subject.
- *"actor is the party the duty falls on, copied from the statement"* against ADR-033's
  instruction that an `ASSIGNED` actor comes from the role heading *above* the item — where it is
  correctly absent from the statement, in 31 of 31 cases.

Both had been shipped and read repeatedly. Listing the rules found them in minutes.

## Decision

**Every rule the prompt states is registered in code, and each is either bound to the validator
that enforces it or carries a written reason why it cannot be.** A test asserts the registry and
the prompt have not drifted apart.

1. **A registry, not a rewritten prompt.** `PROMPT_RULES` holds one entry per rule: an id, the
   sentence as it appears in the prompt, and either `enforced_by` naming a validator or
   `unenforceable` giving the reason. The prompt stays prose that a person can read and edit.
2. **The test asserts three things.** Every registered sentence appears verbatim in
   `EXTRACTION_PROMPT`, so editing the prompt without updating the registry fails. Every rule has
   exactly one of `enforced_by` or `unenforceable`, so a rule cannot be added without someone
   deciding which it is. Every `enforced_by` names something that exists.
3. **Adding a rule to the prompt is what fails the test.** That is the whole mechanism: the cost of
   writing an unenforced rule moves from "discovered a sprint later in the data" to "the suite is
   red before the commit".
4. **`unenforceable` is a first-class answer, and must give a reason rather than a shrug.**
   Roughly half these rules need judgement. A registry that pretended otherwise would push people
   to write bad validators to get past the gate, which is worse than the problem.

## Consequences

**It proves a link, not a correctness.** The test asserts that a rule names a validator; it cannot
assert the validator implements that rule. A wrong validator passes. This is a real limit and is
stated because the alternative — believing the registry means the rules hold — would rebuild the
same false confidence one level up.

**The prompt's two self-contradictions have to be resolved to register the rules at all**, since
neither sentence is true as written once `ASSIGNED` exists. That is work this decision creates
rather than avoids, and it is the right kind: the contradictions are already shipped and already
confusing the model.

**It does not help with rules the prompt does not state.** The `ASSIGNED` actor rule lives in
ADR-033 and in the prompt's ASSIGNED section, not in its general actor sentence. A registry keyed
on prompt sentences records what the prompt says, which is the scope, not everything the extractor
requires.

## Alternatives considered

**Generate the prompt text from the validators.** The strongest guarantee: the two could not
diverge because there would be one source. Rejected for now because roughly half the rules are
unenforceable and would have to live somewhere else anyway, so the prompt would become two
documents stitched together — and because it would rewrite the file whose last two edits each moved
every extraction number, in the same change as a mechanism meant to increase confidence.

**A standing review question — "does this rule have a validator?"** Cheapest, and rejected because
it is precisely what the last four sprints believed they were doing. Sprint 9's retrospective
already carries "when a guard requires a field, assume a model will find the cheapest way to fill
it" as a standing action; standing actions did not prevent the fourth instance.

**Assert coverage by counting.** A test that the number of validators is at least the number of
checkable rules. Rejected as the kind of check that passes while naming nothing — it would go green
on any two validators for two unrelated rules.
