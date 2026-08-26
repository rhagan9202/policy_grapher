# STORY-088: An unparseable item costs what the ADR says it costs

**Epic:** — · **Status:** Ready · **Estimate:** M

## User story

As a policy analyst reading an edition, I want a single malformed sentence in the model's answer
to cost only itself, so that a fifth of the document does not disappear because one sentence
states scope rather than duty.

## Context

The implementation half of [STORY-087](STORY-087-the-blast-radius-of-an-unparseable-item-is-decided.md),
and it must not start before that decision is recorded. Measured on 2026-08-26: 8 of 37 chunks
rejected whole, all `modality: null`, each one losing every obligation in that chunk rather than
the one sentence the model could not label.

The strictness lives in the adapter — `LocalExtractor.extract` raises `ValueError` when any item
fails `ExtractedObligation.model_validate`, and `rebuild_derived` catches it per chunk. Both
sides move together, so this is one change across a port boundary rather than a local edit.

## Acceptance criteria

- [ ] The behaviour matches what STORY-087's ADR decided. If it decided the chunk keeps its
      valid items, a chunk with one bad item writes the rest.
- [ ] Given a chunk whose model output contains one invalid item and three valid ones,
      **When** it is extracted, **Then** the outcome is what the ADR specifies, and a test names
      the ADR.
- [ ] Whatever is discarded is counted, and the count reaches the screen — an edition that lost
      items must still be able to say it is incomplete, which is what STORY-057 established and
      what a silent drop would undo.
- [ ] The extraction ratchet is re-measured afterwards and its floors updated if they move,
      recording the observed numbers as `FLOORS` has always done.
- [ ] Given the model returns nothing valid at all, **Then** that is still a failure and still
      says so — tolerating a bad item must not turn a wholly broken model into a green run,
      which is the property `rebuild_derived` already guards.

## Dependencies

- **STORY-087 must land first.** This item is deliberately not startable without it; a
  boundary change made before the decision is the decision.
- Touches `backend/src/policy_grapher/extraction/local.py` and
  `backend/src/policy_grapher/links/rebuild.py`, and the ratchet measures the result.

## Open questions

- None once the ADR lands. That is the point of splitting them.
