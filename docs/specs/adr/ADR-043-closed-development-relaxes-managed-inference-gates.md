# ADR-043: Closed development relaxes the managed-inference gates for the Azure adapter

**Status:** Accepted · **Date:** 2026-09-23 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-041](ADR-041-accredited-managed-inference-is-permitted.md) and
[ADR-020](ADR-020-model-weights-come-from-us-organisations.md)**, for one adapter and for as long
as the condition below holds.

## Context

The project is in closed development and testing. The project owner has Azure Government OpenAI
deployments of gpt-4o, gpt-5.1 and gpt-5.6-luna, reachable with an API key, and wants obligation
extraction to run through them now.

Three gates stand in front of a managed extractor as the decisions are written. ADR-041 lets an
adapter send corpus text off the machine only when it records the accreditation it relies on.
ADR-020 requires the served model to be in the US-origin set, a test-held list with no GPT model in
it. The two-adapter plan (docs/plans/2026-09-22-1130-feat-two-adapters-ingestion-and-managed-extraction-plan.md)
adds measured floors, and a gate that fails rather than skips without them. None of the three can be
honestly produced yet: nobody has recorded an accreditation, no supply-chain decision has added a
GPT model, and floors are a measurement of a model this machine cannot call.

## Options considered

**Keep every gate, and wait.** Rejected. It leaves extraction on CPU at ninety seconds a chunk
through the whole of closed development, for material that is not yet what the gates protect.

**Build the adapter and leave the ADRs as they are.** Rejected. The code would contradict two
accepted decisions, and the next reader would be right to "fix" it back.

**Relax the gates for this adapter, in writing, with a named end.** Chosen.

## Decision

While the corpus is in closed development and holds no real controlled unclassified information,
the Azure OpenAI extraction adapter (`EXTRACTOR_ADAPTER=azure`):

- may send corpus text to an `https://*.azure.us` endpoint **without an ADR-041 accreditation
  record**. The host restriction and the https requirement stay, checked at startup;
- may serve a model that is **not in ADR-020's US-origin set**;
- runs **without recorded floors**. The floors tests skip for it loudly, as they do for any adapter
  nobody has measured, and the responsibilities-coverage test follows the same rule.

The `null` default stands, so a fresh clone and CI still run with no model and no key.

**What ends it.** Either the first real CUI entering the corpus, or any use beyond closed
development and testing, whichever comes first. At that point this ADR is superseded, and the gates
return: ADR-041's accreditation record, an ADR-020 set entry made by its own recorded decision, and
the two-adapter plan's U3–U6.

## Consequences

A working managed extractor exists now, fast enough for extraction to stop being an overnight job.

The debt is explicit, dated and has a trigger, rather than being an absence someone has to notice.
Whoever brings real CUI into the corpus meets this ADR first, because `.env.example` and the
adapter's docstring both cite it.

Extraction quality through this adapter is unmeasured. Reasoning models cannot be pinned to
temperature 0, so when floors are measured, they will need repeated runs.
