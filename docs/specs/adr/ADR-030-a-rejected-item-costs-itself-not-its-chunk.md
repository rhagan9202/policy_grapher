# ADR-030: A rejected item costs itself, not its chunk

**Status:** Accepted · **Date:** 2026-08-26 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-023](ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)**, which moved the
blast radius from the run to the chunk. This moves it one level further, to the item, and keeps
everything else ADR-023 decided.

## Context

ADR-023 was written when a rebuild failed at chunk 5 of 38 because the model returned
`modality: null` for one sentence. Its formula was exact: **the extractor stays strict, the
batch tolerates.** It applied that to one boundary — the run tolerates a bad chunk — and left
the chunk itself intolerant, because at the time that was the boundary in front of it.

Sprint 6 made the remaining cost measurable. `PROMPT_VERSION 2` was written to stop the model
recording section headings as obligations and dropping sentence subjects; it moved precision
0.294 → 0.625 and recall 0.385 → 0.769 against the gold set. It also took the rejection rate
from **2 chunks in 37 to 8 in 37**.

Every one of those eight was `modality: null`, on a sentence stating scope rather than duty —
"This issuance applies to the OSD, the Military Departments..." — where the model has no modal
verb to report and emits null rather than omitting the sentence. Three prompt variants were tried
against it in sprint 6: rewording the rule, removing the quoted negative example, and
generalising the negatives. None moved it. That is what makes this a boundary question rather
than a wording one.

**The cost is not proportionate to the error.** One sentence the model could not label discards
every obligation in its chunk. At eight chunks in thirty-seven, roughly a fifth of a document is
lost to recover nothing.

## Decision

**A chunk keeps the items that validate, and reports the ones that did not.**

1. **The extractor still validates every item strictly.** `Modality` stays closed. Nothing about
   what counts as a valid obligation changes — this is about what a single invalid one costs,
   not about accepting it.
2. **An item that fails validation is dropped, and counted.** The chunk writes its remaining
   valid items.
3. **A chunk where *nothing* validates is still a rejected chunk**, reported as ADR-023 already
   reports one. Tolerating a bad item must not turn a wholly broken model into a green run, which
   is the property `rebuild_derived` already guards and which this must not weaken.
4. **Dropped items are reported the way rejected chunks are** — a count, and enough of the reason
   to see the shape of the failure. STORY-057 established that a count alone tells an operator an
   edition is incomplete without saying what is missing from it; the same bar applies here.

## Consequences

**What this buys.** Roughly four fifths of what is currently discarded. On the 2026-08-26
measurement, eight chunks lost whole becomes eight *sentences* lost, and the obligations that
shared those chunks survive.

**What it gives up, and this is the real cost.** ADR-023 leaned on loud failure: an adapter that
invents a binding level must fail where someone sees it. Dropping items quietly is exactly the
shape that argument warns about, and this project's own history is full of checks that stopped
being able to fail. **The count is what keeps it honest**, and it is a weaker guarantee than a
refusal — a number in a report is easier to not read than a run that stops.

Two things follow from accepting that. The count is not optional and not a nice-to-have: an
implementation that drops items without reporting them has implemented something this ADR did
not decide. And the extraction ratchet becomes the check that matters more, because it measures
what the model gets *right* rather than what it got wrong loudly enough to notice — which is why
sprint 6 spent an item making that gate able to fail at all.

**What it does not change.** A rejected chunk still costs its chunk and not the run. A rejected
item was always the model's fault and still is. The remedy for a high drop rate is a better
prompt or a better model, not a looser schema — the same sentence ADR-023 ends on, one level
down.

**Why not fix the prompt instead.** That was tried first and is what produced the measurement
above. Three variants, no movement. The model is deterministic at temperature 0, so a retry
returns the same answer and re-extraction is not a remedy either. The sentences it fails on are
a real category — scope statements that name no duty — and asking a model to omit them rather
than label them null is asking for a judgement it demonstrably does not make reliably.
