# STORY-103: The prompt stops contradicting itself about ASSIGNED

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As the model reading the extraction prompt, I want its rules to be true of every modality it names,
so that two sentences do not tell me opposite things about the same field.

## Context

Found by [ADR-036](../../specs/adr/ADR-036-a-checkable-prompt-rule-is-checked.md) while enumerating
the prompt's rules to register them. Both contradictions were introduced by
[ADR-033](../../specs/adr/ADR-033-a-duty-can-be-assigned-by-position.md), both have shipped, and
neither was noticed until the rules were listed side by side — reading the prompt top to bottom
several times did not surface them.

**1. The statement's subject.** The prompt says a statement must be copied *"as a complete sentence
including the subject that carries the duty"* and *"do not begin the statement at the verb"*.
ADR-033 requires an `ASSIGNED` statement to be the lettered item — `"Executes the acquisition
responsibilities in DoDD 5135.02."` — which begins at the verb and carries no subject.

**2. Where the actor comes from.** The prompt says *"actor is the party the duty falls on, copied
from the statement"*. ADR-033 takes an `ASSIGNED` actor from the role heading *above* the item,
where it is correctly absent from the statement — 31 of 31 such obligations in the graph.

The second contradiction is the more interesting one, because the model appears to have resolved it
in the prompt's favour at least once: sprint 10 measured 14 of 123 word-modality actors that were
not in their statement, and [ADR-035](../../specs/adr/ADR-035-an-actor-is-validated-before-it-is-canonicalised.md)
now refuses them. Whether the contradiction contributed cannot be known without fixing it and
re-measuring, which is this story.

## Why it was not fixed when it was found

**Correcting the prompt bumps `PROMPT_VERSION`, which invalidates the extraction cache and forces a
full re-extraction of every edition.** It was found mid-sprint with three rebuilds already running
under the current version, and bumping would have discarded them. Deferred deliberately, recorded
here rather than carried in anyone's head.

## Acceptance criteria

- [ ] Both sentences are corrected so they are true of all six modalities — stating the general
      rule and naming `ASSIGNED`'s exception, rather than stating a rule that is false for a sixth
      of the enum.
- [ ] `PROMPT_VERSION` is bumped in the same commit, and the review records that the cache was
      invalidated deliberately.
- [ ] `PROMPT_RULES` is updated: `statement-includes-the-subject` currently carries an
      `unenforceable` reason that begins "Contradicted by ADR-033 and therefore not true as
      written". After this story that clause is false and must go — the remaining reason (a
      sentence-fragment judgement needs a parser) stands on its own.
- [ ] The floors are re-measured three times at temperature 0 afterwards, as any prompt change
      requires, and any movement is reported. **Truncated below the lowest observation, never
      rounded to it** — sprint 9 recorded a floor above its own measurement and the gate failed on
      itself.
- [ ] The actor-not-in-statement rate is re-measured against the 14 of 123 recorded before the fix,
      and the review says whether the contradiction was contributing.

## Dependencies

- None. It should not be started in the same session as a rebuild whose results anyone wants to
  keep, for the reason above.

## Notes

The general lesson is worth more than the two sentences: **an ADR that adds a case to an existing
rule has to revisit the prose that states the rule.** ADR-033 changed what `Modality` means and
what an actor is for, and updated the prompt's `ASSIGNED` section while leaving two general
sentences that its change had falsified.
