# ADR-041: The bar for inference is accreditation, not locality

**Status:** Accepted · **Date:** 2026-09-17 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-016](ADR-016-embeddings-are-a-port.md)**, which made the embedder a port with a null
default and required the model run locally. This replaces the locality requirement with an
accreditation requirement, and keeps everything else ADR-016 decided.

## Context

ADR-016 rejected a hosted embedding API on two grounds, and named the second decisive: test runs
would need network and a key, and *"the material this corpus is heading toward is controlled
unclassified information, which cannot be sent to a third-party API at all."*

The first ground no longer argues for locality. ADR-016 itself answered it with the null default —
a fresh clone and CI pass with no model downloaded and no key configured. That property comes from
the port, not from where the adapter runs.

The second ground is sound and stays sound. What is wrong with it is narrower: it treats *hosted*
and *unaccredited* as the same word. In the environment this corpus belongs to they are not. A
managed service operating inside an accreditation boundary that covers CUI is authorised to process
exactly this material; that is what the accreditation is for. ADR-016 excluded a class of service on
a property — topology — that is not the property its own reasoning cares about.

The cost of the conflation is now measurable. Local inference on the shipped stack runs at roughly
seven tokens a second, about ninety seconds a chunk, and editions run from thirty-seven to two
hundred and four chunks. That is the number that keeps clause-level extraction out of any
interactive path, and it is a property of the hardware on hand rather than of the work.

## Options considered

**Keep the prohibition as written.** Simple, and it never has to be revisited. Rejected: it excludes
a class of service that is accredited for this material, and it does so by naming the wrong
property. The cost is not abstract — extraction stays a batch job indefinitely, or it stays bounded
by whatever accelerator someone can attach to the machine.

**Permit any hosted provider, and rely on operator judgment.** Rejected outright. ADR-016's second
ground is correct: an unaccredited endpoint is precisely what it excludes, and "the operator will
check" is the kind of control that holds until the first hurried afternoon.

**Permit a managed service that holds an accreditation covering the material, and record which
one.** Chosen. It keeps the constraint ADR-016 was actually defending while letting the decision
turn on the fact that governs it.

## Decision

**The constraint is accreditation, not locality.** An adapter may send corpus text to a managed
service when that service holds an accreditation covering the classification of the material being
sent. A service without one is excluded exactly as before — this widens the gate by a named
property, it does not open it.

**The accreditation is recorded, not assumed.** An adapter that sends text off the machine records
which accreditation it relies on, at what level, covering what material, and where that was
verified. An adapter that cannot name its accreditation is an unaccredited adapter.

**The null default stands.** It is what keeps a fresh clone and CI working with no model and no key,
which was ADR-016's first ground and remains true for reasons this ADR does not touch.

**[ADR-020](ADR-020-model-weights-come-from-us-organisations.md) is unaffected and still binds.** A
managed endpoint's served model must satisfy the US-origin provenance set, or that set is widened by
its own recorded supply-chain decision. Accreditation of the service and provenance of the weights
are different questions, and clearing one does not clear the other.

**Everything else ADR-016 decided stands.** The embedder remains a port. The null embedder still
returns no vectors rather than zero vectors. The index still records whose vectors it holds, which
is the protection against the silent-mismatch failure that was most of ADR-016's substance and is
untouched by where the model runs.

## Consequences

Clause-level extraction becomes fast enough to sit in an interactive path, which is what makes a
dependency map that expands into clauses worth building.

It commits the project to treating an accreditation as a recorded fact with a shelf life. An
accreditation lapses, changes scope, or turns out not to cover what someone assumed; a recorded one
can be re-checked, and an assumed one cannot.

It makes the adapter boundary the place where egress is decided, which is where the null default
already lives. That is a good place for it and a load-bearing one: a future adapter that sends text
somewhere new inherits this rule by being an adapter, not by anyone remembering this ADR.

The silent-mismatch hazard ADR-016 spent most of its length on gets slightly worse in one respect —
a managed model can change underneath a stable name without any local version moving. The index's
provenance record is the existing answer and it still applies, but a hosted `model_id` is a weaker
identity than a local one, and that is a known cost of this change rather than an oversight.
