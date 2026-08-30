# STORY-108: Actor accuracy is measured

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As someone deciding what to do about actors, I want the extractor's actor accuracy scored against
the gold set, so that the decision argues from a number rather than from an impression.

## Context

[ADR-035](../../specs/adr/ADR-035-an-actor-is-validated-before-it-is-canonicalised.md) deferred
canonicalising actors and named the prerequisite in as many words: *"nothing measures actors at
all. The ratchet scores precision, recall and modality accuracy; actor is not scored on any leg.
That is the gap to close before this decision is revisited."*

Nothing has closed it, and sprint 11 added to the pile without meaning to — paragraph 2.6 returns
`DOD CHIEF INFORMATION OFFICER`, as its heading writes it, which is a third spelling of an office
already recorded two ways.

**Measured at sprint 12 planning, over the 25 matched pairs in the gold set:**

| Comparison | Accuracy |
| --- | ---: |
| Exact string | **0.600** |
| Case-folded and trimmed | **0.840** |

Six of the ten disagreements are case alone. **Every one of the remaining four is the same thing,
and it is not an error:**

    predicted 'DIRECTOR OF OPERATIONAL TEST AND EVALUATION'  ->  gold 'DOT&E'

The heading reads `2.7. DIRECTOR OF OPERATIONAL TEST AND EVALUATION (DOT&E).` The model took the
title; the gold fixture took the parenthetical abbreviation. **Both name the same office and both
are defensible**, which makes this a question about what the gold set should say before it is a
question about the extractor.

## The decision this needs

**What counts as the right actor when the document gives two names for one office?** Three answers,
and the choice determines what the floor measures:

- **The title as written above the item.** What the model does now. Verbose, and it varies with the
  heading's own capitalisation.
- **The abbreviation the document defines.** What the gold set does now. Compact and stable, and it
  requires resolving `(DOT&E)` out of the heading — which is a parse, not a copy.
- **Either, scored as equivalent.** Honest about the document, and it needs an equivalence notion
  the scorer does not have.

## Acceptance criteria

- [ ] `score()` gains an actor leg, scored over matched pairs the way `modality_accuracy` is, so a
      passage where nothing matched contributes nothing rather than a vacuous 1.0.
- [ ] The comparison is decided and the reason recorded — case-folded at minimum, since six of ten
      disagreements are case alone and no reading of the document makes `DoD CIO` and `DOD CIO`
      different offices.
- [ ] The gold set is made consistent with whatever is decided, and each fixture's `note` says
      which convention it follows.
- [ ] A floor is recorded, truncated below the observation with headroom for one pair — over 25
      pairs one disagreement is 0.04, and a floor that fires on one differing answer teaches people
      to ignore it.
- [ ] The floor is measured three times at temperature 0, like every other floor in that file.
- [ ] Mutation: an extractor that returns the wrong office for one matched pair must fail it.

## Dependencies

- None to start. It unblocks
  [STORY-100](STORY-100-an-office-is-one-actor-not-several-spellings.md) and, behind it,
  STORY-021's `:Entity` work.

## Notes

**Do not let this become canonicalisation.** ADR-035 refused to canonicalise a field nothing scores,
and the answer is to score it, not to skip ahead. A scorer that treated `DOT&E` and
`DIRECTOR OF OPERATIONAL TEST AND EVALUATION` as equal is already a small canonicalisation, which
is why the choice above is a decision and not a detail.
