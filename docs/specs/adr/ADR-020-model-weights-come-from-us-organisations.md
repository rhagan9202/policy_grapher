# ADR-020: Model weights come from US organisations

**Status:** Accepted · **Date:** 2026-08-21 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-016](ADR-016-embeddings-are-a-port.md) ruled out hosted inference for this corpus, on the
grounds that the material is heading toward controlled unclassified information and cannot be
sent to a third-party API. That decision was about *where inference happens*. It said nothing
about *where the weights come from*, and until now neither did anything else.

The default extraction model was `qwen3:8b` — capable, well-suited to the task, and published
by Alibaba. It arrived by the ordinary route such defaults arrive by: it was a good model at a
convenient size, named in a plan, and nobody asked the question. The extraction ratchet's
recorded floors were keyed to it, so it was also the model the project's one quality gate was
built around.

The question was asked when a model server was finally added to the stack.

## Decision

**The default extraction model must be published by a US organisation.** The default is now
`llama3.1:8b` (Meta). `granite3.3:8b` (IBM), `phi4:14b` (Microsoft) and `llama3.2:3b` (Meta)
are the other members of the allowed set today.

**The constraint is provenance, not capability.** Qwen and DeepSeek are excluded regardless of
how they score. This is not a claim that they are worse — on published benchmarks several are
competitive with or better than the model chosen here. It is a claim that for a system whose
purpose is reading Department of Defense policy, and whose corpus is moving toward CUI, where
the weights were produced is a procurement question that outranks the leaderboard.

**It is enforced by a test, not by a convention.** `test_the_default_extraction_model_is_us_origin`
asserts the configured default is in an explicit `US_ORIGIN_MODELS` set. Adding to that set is
a supply-chain decision and shows up in review as one. A comment in `config.py` would have been
forgotten inside a year.

**A second test pins the gate to the shipped model.**
`test_the_shipped_model_has_recorded_floors` asserts the default model's `adapter_id` has an
entry in the ratchet's `FLOORS`. Without it, changing the model silently makes the ratchet skip
— it reports "no floors recorded" and a green suite means nothing was checked. That was the
exact state this project would have entered by changing the model default alone, and the test
exists because the change nearly did it.

## Consequences

**Makes easy.** The provenance question is answered once, in a place a reviewer will see, for
every future model choice — including the day a hosted adapter is considered and ADR-016's
constraint is revisited. Swapping models stays a one-line settings change, because extraction
is a port.

**Makes hard.** The eligible set is smaller, and the frontier moves fastest in models this
excludes. When a non-US model is clearly better at reading policy prose — which is likely,
and may already be true — that gap is a cost this project accepts rather than a problem to
solve. Anyone tempted to relax it should write the superseding ADR rather than edit the set.

**A related gap this ADR does not close.** The default *embedding* model is
`sentence-transformers/all-MiniLM-L6-v2`, distilled from Microsoft's MiniLM but published by
the UKP Lab at TU Darmstadt. It is not US-published, and it is not covered by the set above,
which governs extraction only. Changing it means re-embedding the corpus (ADR-016), so it is
deliberately left for a decision of its own rather than folded in here — but it should not be
left indefinitely, and it is the first thing to check if this constraint is ever audited.

**Commits us to.** Treating model provenance as part of this system's supply chain rather than
as an implementation detail. The moment one model is chosen purely on benchmark score, the
allowlist stops meaning anything — a set that bends for a good enough model is not a
constraint, it is a preference with extra steps.
