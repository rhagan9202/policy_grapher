# STORY-102: A prompt rule nobody checks is not a rule

**Epic:** — · **Status:** Done · **Estimate:** L

## User story

As a maintainer adding a rule to the extraction prompt, I want to know whether that rule is
enforced anywhere, so that I stop discovering months later that the model never obeyed it.

## Context

Three sprints, three instances of the same failure:

| Rule, as the prompt states it | Since | Found | How much it was broken |
| --- | --- | --- | --- |
| The modality word must appear in the statement | v2, sprint 6 | Sprint 7 | 18 of 215 obligations were headings labelled `SHALL` |
| The statement must be copied word for word | v2, sprint 6 | Sprint 9 | 34 of 196, 17%, are not quotations |
| Never write a placeholder actor — use null | v2, sprint 6 | Sprint 9 | 20 obligations carry the string `"null"` |

Every one was written into the prompt in the same sprint. Every one was unenforced for at least
one sprint after. Every one was eventually found by looking at the data rather than by a test —
and each was then fixed deterministically in `schema.py` in under an hour, because the rule was
always checkable.

**The pattern is not that the model disobeys.** It is that a prompt is the only place some rules
live, prompts are not executable, and nothing in this project connects the two. A rule in the
prompt reads exactly like a rule that is enforced.

## The decision this needs

**L because the shape is undecided, per the [estimation scale](../README.md#estimation).** At
least three approaches exist:

- **Enumerate the prompt's rules and assert each has a validator.** A test that fails when the
  prompt gains a checkable rule with nothing behind it. Requires the rules to be machine-readable
  in the prompt — a marked list rather than prose — which changes how the prompt is written.
- **Move the checkable rules out of the prompt entirely** and generate that part of the prompt
  text from the validators, so the two cannot diverge. Strongest guarantee; the prompt stops being
  a document a person edits freely.
- **A standing review question** rather than a mechanism: "does this rule have a validator?" asked
  whenever the prompt changes. Cheapest, and the weakest — it is what the last three sprints
  already believed they were doing.

**Not every prompt rule is checkable**, and the decision has to say what happens to the rest.
"Do not infer a duty that is not written" cannot be validated deterministically; "quote the whole
sentence including its closing full stop" probably can.

## Dependencies

- None. The evidence is in sprints 7 and 9.

## Open questions

- How many rules does the current prompt actually state, and how many of them are checkable? Nobody
  has counted, and the answer decides whether this is a small mechanism or a large one.
- Does a validator without a prompt rule matter too? The reverse direction — the schema refusing
  something the prompt never asked for — wastes a model call per occurrence and is invisible in
  the same way.
