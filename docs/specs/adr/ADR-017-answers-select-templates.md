# ADR-017: Answers select templates, and carry citations or decline

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

`POST /ask` is the surface a person actually touches. Everything under it — editions, chunks,
obligations, human-approved links, changes — exists so that a question in ordinary English can
be answered from the corpus rather than from a model's recollection.

Two things make that dangerous in a way an ordinary chatbot is not.

The first is that **the corpus is text supplied from outside this organisation**. DoD issuances
are ingested wholesale, and nothing in them is under our control. A component that turns
retrieved text into a query, or lets retrieved text influence what query runs, has handed an
outside author a channel into the database. [ADR-009](ADR-009-query-is-read-only-and-bounded.md)
made `POST /query` read-only and bounded, which limits the blast radius considerably. It does
not remove it, and "bounded remote code execution" is not a security posture.

The second is that **a wrong answer here is not a wrong answer, it is a compliance failure**.
Someone asks whether a duty applies, gets a fluent paragraph, and acts on it. A model asked to
answer from retrieved passages will, when the passages are thin, produce something plausible
anyway — that is what the objective rewards. An instruction to cite its sources is advice, and
advice is not a guarantee.

## Options considered

**Text-to-Cypher.** Let a model write the query from the question. Maximum flexibility, and the
obvious thing to build. Rejected outright: it is the injection sink described above, and the
read-only bound does not fix it — a read-only query can still exfiltrate everything in the
graph, and a question is not the only untrusted text in the system.

**Generative RAG with a citation instruction.** Retrieve passages, hand them to a model, ask it
to answer using only those and to cite them. The standard design. Rejected for this system: the
citation requirement is enforced by a prompt, so it holds until it does not, and the failure is
a fluent answer with a plausible citation attached to a claim the passage does not support.
That failure is invisible to everyone except a reader who goes and checks — which is precisely
the work the tool was meant to save.

**A fixed template set, chosen by rule, answered extractively.** Chosen.

## Decision

**No Cypher is ever authored from a question.** `retrieval/templates.py` holds a fixed set of
queries written in advance by a person. A question can only *choose* among them and supply
values, which are bound as query parameters and never interpolated into query text. Two static
tests enforce this rather than trusting it: one asserts no template contains a write clause,
the other that every declared parameter appears as `$parameter` in its own query.

**Selection is a deterministic rule, not a model.** `select_template` matches a small number of
anchored patterns. This is not a placeholder awaiting a model — it means a question cannot
influence *which* query runs except through rules visible in one file, so there is no prompt to
inject into. A model-backed selector could be added later behind the same `Selection` return
type, which is why the route already refuses a selection naming a template that is not in
`TEMPLATES`, with a 500 rather than a passthrough.

**Execution is a read transaction as well.** `RoutingControl.READ` is belt and braces over the
static no-write check: Neo4j refuses a write inside a read transaction, so a template edited
carelessly in future still cannot mutate.

**The answer is composed from the retrieved rows, not written about them.** `_compose` builds
the answer text out of the quotations themselves. There is no step at which a sentence can enter
without a passage behind it — a stronger guarantee than instructing a model to cite, because it
is arithmetic rather than advice. The cost is that answers read as a structured list of
quotations rather than as prose, which is a real loss of fluency and a deliberate one. A model
could later render prose *from these same rows* behind a port; the citations requirement is what
would keep that safe, and it would need its own ADR.

**Every answer carries citations, or states the absence.** There are exactly two shapes of
response: one with at least one citation, and one whose answer says nothing in the corpus
addresses the question with an empty citation list. The absence is phrased as an absence of
evidence rather than as a negative finding, because "the corpus does not say" and "the answer is
no" are different, and a compliance reader must not read the first as the second.

**A structured template that matches nothing falls back to retrieval before declining.** The
passage may be there under different words than the template's traversal expects. The response
reports `grounded_passages` in that case, so `template_used` describes what actually answered
rather than what was first attempted.

**Every template is executed against a real database in the suite.** A template is a string
until something runs it, and the selection rules mean some are reached only by one phrasing that
no route test might happen to use. A parameterised test runs each one, so a typo cannot wait for
production. This caught a real defect while it was being written — two editions of one
instrument seeded under separate slugs violate `Document.name` uniqueness — which is the kind of
thing that only surfaces when the query actually executes.

## Consequences

**Makes easy.** The injection surface is a short list of queries a person can read in one
sitting, and the prompt-injection surface is empty because there is no prompt. Answers are
reproducible: the same question against the same graph returns the same text, which makes the
route testable in a way a generative one is not. Adding a question shape is adding a template
and a pattern, both in one file, both immediately covered by the static and execution tests.

**Makes hard.** The system answers three shapes of question well and everything else by
retrieval, and the retrieval answer is a list of quotations rather than a synthesis. A user who
asks a question spanning several passages gets the passages, not the joined-up answer, and must
do the joining. That is the honest cost of refusing to let anything assert what the corpus does
not state, and it will be the most common complaint about this endpoint.

**Commits us to.** Query text in this system being written by people, permanently. The value of
every guard here — the static checks, the read transaction, the bound parameters — collapses the
moment one code path composes a query from input, because a reader can no longer tell by
inspection which queries exist. It also commits the project to `citations == []` meaning exactly
one thing: the corpus was searched and nothing matched. Any future path that returns an answer
without citations for some *other* reason breaks the contract this endpoint's readers depend on.
