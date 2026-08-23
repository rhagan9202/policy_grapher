# ADR-023: A rejected item costs its chunk, not the run

**Status:** Accepted · **Date:** 2026-08-22 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

Sprint 4's Definition-of-Done walkthrough ran a real corpus PDF through the product against
`llama3.1:8b` — the first time that had ever been done, three items into the model work.
[ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md)'s ratchet had only ever run against
curated fixtures.

The rebuild **failed at chunk 5 of 38**:

```
ValueError: model output did not match the obligation schema:
1 validation error for ExtractedObligation
modality
  Input should be 'SHALL', 'MUST', 'SHOULD' or 'MAY'
  [type=enum, input_value=None, input_type=NoneType]
```

`rebuild_edition` raised, RQ marked the job `failed`, and the four chunks that had already
extracted cleanly produced nothing. Reproduced on both editions.

Two things were tangled and only one was wrong. The model returned `modality: null` and
validation rejected it — correct, and deliberate: `extraction/schema.py` says "SHALL misread as
SHOULD downgrades a binding duty to advice, silently — so an adapter that invents a value must
fail loudly." Loud failure on a bad *item* is the design working.

Loud failure on one item ending the whole *run* was never decided. It was the default that
falls out of a bare `for` loop, and it made the sprint's own acceptance criterion unreachable:
with `EXTRACTOR_ADAPTER=null` there are no obligations, and with `local` there was no run.

## Decision

**The extractor stays strict. The batch tolerates.**

1. **`rebuild_derived` catches `ValueError` per chunk** and carries on. Nothing changes in
   `LocalExtractor` or `ExtractedObligation`: an adapter that cannot parse a response still
   raises, and the ratchet still measures extraction quality against a strict schema. Putting
   the tolerance in the adapter would have hidden the failures from the one thing measuring
   them.
2. **The count is reported.** `chunks_rejected` is always present in a rebuild's counts, so a
   run with zero rejections is distinguishable from a run by an older build that never counted.
   It reaches the operator through `GET /rebuilds/{run_id}` with everything else.
3. **A run in which *every* chunk was rejected raises `ExtractionFailed`.** This is the line
   that keeps the tolerance honest. Nothing downstream can tell "this edition states no
   obligations" from "the extractor answered garbage 38 times", and the second is not a result.
   The same reasoning as [ADR-016](ADR-016-embeddings-are-a-port.md)'s refusal to accept a
   silently mismatched index, and [ADR-019](ADR-019-the-first-run-is-empty.md)'s refusal to let
   an empty screen read as a worked-through queue.

## Consequences

**Makes easy.** A rebuild against a real model completes. That is not a small claim: before
this, no rebuild against a real model had ever completed against this corpus, which is why
sprint 4's second definition-of-done gate could not be met.

**Makes hard.** A partial derived layer is now a state the system can be in — correct for what
it contains, silently incomplete about the rest. `chunks_rejected` is the only thing that says
so, and a reader who does not look at it will not know. That is a real cost and the reason
point 2 is not optional.

**Assumption:** an all-or-nothing threshold is the right shape, rather than "fail if more than
*n*% were rejected". A proportional threshold needs a number nobody can defend yet — the honest
figure comes from [STORY-055](../../backlog/backlog.md#ready), which widens `Modality` and will
change the rejection rate substantially. Revisit then, with data.

## Alternatives considered

**Widen `Modality` so the rejection stops happening.** That is STORY-055 and it is worth doing,
but it is a different decision — about which modalities the corpus actually uses — and it does
not bound the damage when the next unparseable response arrives in some other field. Doing it
instead of this would leave a 38-chunk run one bad token away from total loss.

**Coerce a null modality to a default.** Rejected outright. It is precisely the silent
downgrade `extraction/schema.py` exists to prevent, and picking any default means asserting a
binding level the model declined to assert.

**Retry the chunk.** Considered and not taken: the extractor runs at temperature 0, so a retry
returns the same response. Worth revisiting only if sampling is ever introduced.
