# STORY-105: Responsibilities coverage has a floor

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As a maintainer changing the extractor, I want a floor under how much of a responsibilities section
is read, so that a change which quietly stops reading a role section fails rather than shipping.

## Context

The extraction ratchet floors precision, recall and modality accuracy against a gold set of six
passages. **It cannot see coverage.** A change that stops reading four role sections entirely
leaves every gold fixture passing, because no fixture comes from those sections — which is exactly
the state sprint 10 shipped in, at 19 of 40 items on DoDD 5000.01 (2020), with the gate green.

This is the same shape as [STORY-073](STORY-073-editions-ratchet-against-their-own-reference-set.md),
which floors how many of an edition's references are found, for the same reason: a per-passage
score says nothing about how much of the document was reached.

## Acceptance criteria

- [ ] A per-document expected count of lettered items under role headings, hand-counted and
      recorded with the count for each role section, not only the total. DoDD 5000.01 (2020) is 40,
      counted at sprint 11 planning.
- [ ] A test floors the proportion actually extracted, per document, and names the role sections
      that yielded nothing when it fails.
- [ ] It skips **loudly** when no model server is reachable, the way the extraction gate does — a
      silent skip here would recreate the gap this story exists to close.
- [ ] The floor is recorded as measured, truncated below the observation, with the same reasoning
      the extraction floors carry.
- [ ] Mutation: making the extractor ignore one role section must fail this test.

## Dependencies

- [STORY-104](STORY-104-assigned-recognises-the-role-headings-dod-writes.md) should land first, so
  the floor is set on the improved extractor rather than on 48%.

## Open questions

- One document or all seven? Hand-counting every sample is real work, and a floor on one document
  catches a general regression while a floor on seven catches a document-specific one. Starting
  with the two DoDD 5000.01 editions gives a before-and-after pair on the same instrument.
- Does this belong in the ratchet file or its own? The ratchet measures an adapter against gold
  passages; this measures an adapter against whole documents. Same purpose, different unit.
