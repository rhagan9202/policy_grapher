# STORY-095: The rejection rate is diagnosed

**Epic:** — · **Status:** Done · **Estimate:** M

## User story

As a maintainer deciding what to fix next, I want to know whether half of each document yields
nothing because of the prompt, the model, or the chunker, so that the fix is chosen from evidence
rather than from whichever is easiest to change.

## Context

Sprint 7's retrospective assigned this and sprint 8's planning deferred it once. Measured on the
2026-08-27 rebuild of DoDD 5000.01's 2020 edition:

    37 chunks    20 rejected whole    85 further statements dropped    56 obligations kept

A rejected chunk is not a passage without duties. It is one where the model returned items and
**none** of them validated — so the model is over-extracting, and the schema is refusing what it
returns. The failures are consistent: headings ("e. Emphasize Competition."), scope statements,
and preamble, each labelled SHALL with no SHALL in the sentence.

Three explanations are live and they imply different fixes:

- **The prompt.** It already asks for exactly what the schema enforces. Sprint 6 tried three
  variants against the related rejection problem and none moved it, so this is the least likely
  and the cheapest to re-test.
- **The model.** `llama3.1:8b` may simply not distinguish a heading from a duty reliably at this
  size. ADR-013 made the extractor a port precisely so this could be answered by swapping one.
- **The chunker.** A chunk that is mostly a table of contents or a list of section titles gives
  the model nothing else to find, and asking it to return an empty list from a page of headings
  may be the unreasonable request. If so the fix is upstream of extraction entirely.

**The instrument now exists.** The ratchet scores precision, recall and modality accuracy
separately against a five-fixture gold set, it fails when it should, and it is deterministic at
temperature 0. Sprint 6 built it and sprint 7 proved it catches real regressions.

## Acceptance criteria

- [ ] The rejected chunks from a real rebuild are characterised: what they contain, and what
      proportion are dominated by headings, tables of contents, or front and back matter.
- [ ] Each of the three explanations is tested against evidence rather than argued. At minimum:
      the current prompt re-run against a chunk sample; a second model through the same port; and
      the rejection rate measured per section kind.
- [ ] The finding names which explanation the evidence supports and what it would take to fix,
      including "more than one of them".
- [ ] The finding is written down where the next person will find it — an ADR if it changes a
      decision, the sprint review if it does not.
- [ ] Whatever the answer, the extraction floors are re-measured afterwards if anything changed,
      and recorded as observed.
- [ ] Given the evidence is inconclusive, **Then** that is the finding and it says what further
      evidence would settle it — an honest "we do not know yet" is a result and a guess is not.

## Dependencies

- The extraction ratchet and its gold set, both landed.
- A second model through the extractor port, if that explanation is tested — which needs pulling
  weights and is the slowest part of this item.

## Open questions

- None that block starting. The point of the item is to answer the ones it names.

## Notes

**This is a spike whose output is an answer, not a fix.** If the evidence points at the model or
the chunker, the fix is a separate item and probably a large one. Committing to the fix here
would be committing to work whose shape is unknown, which is the thing this is meant to prevent.
