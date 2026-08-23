# ADR-024: Embedding weights come from US organisations too

**Status:** Accepted · **Date:** 2026-08-23 · **Deciders:** —
**Extends:** [ADR-020](ADR-020-model-weights-come-from-us-organisations.md)

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

[ADR-020](ADR-020-model-weights-come-from-us-organisations.md) constrained *extraction* weights
to US-published models, and closed by naming what it had not covered:

> **A related gap this ADR does not close.** The default *embedding* model is
> `sentence-transformers/all-MiniLM-L6-v2`, distilled from Microsoft's MiniLM but published by
> the UKP Lab at TU Darmstadt. It is not US-published, and it is not covered by the set above,
> which governs extraction only. […] it should not be left indefinitely, and it is the first
> thing to check if this constraint is ever audited.

STORY-060 is that audit. It was written for a different reason — sprint 4 found ADR-020 enforced
by a test that asserted on a developer's shell while `docker-compose.yml` supplied another model
to every container — and the sweep it produced surfaced exactly the gap ADR-020 had flagged.

Two facts decide the timing. `EMBEDDER_ADAPTER` defaults to `null`, so **nothing in this project
has ever been embedded**: the sprint 4 walkthrough's rebuilds reported `embedded: 0` on every
run. And [ADR-016](ADR-016-embeddings-are-a-port.md) records the model on the vector index and
refuses a mismatched one, so changing it after a corpus is embedded means re-embedding that
corpus. The change is free exactly once, and this is that moment.

## Decision

**The provenance constraint covers embedding weights, on the same reasoning and with the same
enforcement.** The default becomes **`Snowflake/snowflake-arctic-embed-s`** (Snowflake Inc., US,
Apache 2.0).

`US_ORIGIN_EMBEDDING_MODELS` is its own set rather than an addition to ADR-020's, because the
two lists answer different questions — no model belongs to both — and a single set would invite
an extraction model being configured as an embedder or the reverse. The eligible set today is
`snowflake-arctic-embed-s`, `snowflake-arctic-embed-m` (both Snowflake Inc.) and
`nomic-embed-text-v1.5` (Nomic AI). `test_the_default_embedding_model_is_us_origin` asserts the
configured default is in it, and STORY-060's `test_config_composition.py` asserts compose does
not quietly supply another — which is the pairing ADR-020 lacked and was violated for its whole
life without anyone noticing.

**`-s` rather than `-m`, and the reason is index geometry.** It produces **384-dimension**
vectors, the same width as the `all-MiniLM-L6-v2` it replaces. Verified by loading it, not
assumed: `dimensions: 384`, deterministic across calls, and it loads through plain
`sentence-transformers` with no `trust_remote_code`. `-m` is a larger model at 768 dimensions
and remains eligible if quality ever justifies the re-embed.

## Consequences

**Makes easy.** The provenance rule now means what its title always said — *model weights*, not
*extraction weights*. A reader no longer has to know that one of the two model ports was
exempt. And because the width is unchanged, nothing about the vector index, `ensure_vector_index`
or the retrieval path changes: this is a one-line settings change and a test, which is what
[ADR-016](ADR-016-embeddings-are-a-port.md)'s port was built to make possible.

**Makes hard.** The eligible embedding set is small and the field moves quickly; several
excluded models are better on published benchmarks, and at least one — `bge` from the Beijing
Academy of AI — is excluded on exactly the provenance grounds ADR-020 set out. That cost is
accepted, not solved. Anyone tempted to relax it writes the superseding ADR rather than editing
the set.

**Assumption:** `arctic-embed-s` is good enough for this corpus. **It has not been measured
here.** There is no embedding ratchet — extraction has one
([ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md)), embedding does not — so this ADR
changes a model on provenance grounds with no quality evidence either way, and the model it
replaces had none either. That is a real gap and it is not this ADR's to close; it becomes
visible the first time `/ask` is used in earnest.

## Alternatives considered

**Leave it, and record the deadline.** Rejected on cost asymmetry. The change is free while
nothing is embedded and becomes a corpus re-embed the moment anything is. ADR-020 already
deferred it once with "it should not be left indefinitely"; deferring again would have set the
same reasoning against a strictly higher price.

**`intfloat/e5-base-v2`.** Strong and widely used, and its author works at Microsoft Research —
but it is published under an individual's account, not an organisation's. A provenance rule that
accepts "employed by a US company" rather than "published by a US organisation" is not the rule
ADR-020 wrote, and the whole point of that ADR is that the constraint does not bend to
convenience.

**Fold the eligible embedding models into `US_ORIGIN_MODELS`.** Rejected: one flat set makes it
possible to configure `llama3.1:8b` as an embedder, or `arctic-embed-s` as an extractor, and
have the provenance test pass while the configuration is nonsense.
