# ADR-013: Extraction is a port, and the swap is a gate

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-012](ADR-012-chunks-follow-sections.md) put the documents' text into the graph as
`:Chunk` nodes bounded by the document's own section structure, and established the shape a
derived layer takes: deterministic identity, drop before write inside one transaction, safe to
discard because nothing about it is a human decision. It stopped deliberately short of reading
those chunks for meaning. This phase reads them: a chunk of policy prose becomes zero or more
`:Obligation` nodes recording who must do what, by when, under what conditions, and how binding
the duty is.

Nothing in this codebase has needed a language model before. `sources/pdf.py` extracts citations
with regular expressions and [SPEC-001](../SPEC-001-di-1-policy-grapher.md) requires it to stay
that way, because a citation is a designator with a fixed surface form and a model is a strictly
worse tool for matching one. An obligation is not like that: "these records must be clearly
marked, not destroyed, and treated as permanent until NARA approves a retention" cannot be
recognised by pattern, and the same passage two paragraphs later says records "may be identified
in the future", which is a prediction wearing a modal verb's clothes. Telling those apart is the
job, and it is the job a model is actually good at.

That introduces a dependency of a kind the project has avoided so far: one whose behaviour is
not specified by its interface, changes when someone else retrains it, and cannot be reproduced
from the repository. Three questions follow, and this ADR answers all three. Where does the
correctness boundary sit when the thing producing the output is not deterministic? What has to
be true before a different provider can be substituted? And how does anyone know the substitution
did not quietly make the graph worse?

## Options considered

**Call a hosted provider directly from ingest.** Fewest moving parts, best available quality
today. Rejected: it makes the provider's availability, pricing and output format a hard
dependency of `uv run pytest`, and it makes the SDK's response schema the de facto definition of
what an obligation is. There would then be no place to stand from which to compare a second
provider against the first.

**A rules engine over modal verbs.** Deterministic, reproducible, no new dependency, consistent
with how citation extraction already works. Rejected on the corpus's own evidence: the mixed
fixture in this phase's gold set contains four modal verbs and two obligations, and the two that
are not obligations ("may result in new categories of records", "may be identified in the
future") are indistinguishable from the two that are without reading the sentence for meaning.
A rules engine reports four, scoring 0.5 precision on a passage a careful reader finds easy.

**A port with a null default and an eval ratchet.** An `ObligationExtractor` protocol, a default
adapter that extracts nothing and needs no infrastructure, a local HTTP adapter for development,
and a hand-labelled gold set that scores any adapter against recorded floors. Chosen.

## Decision

**The model is a port, not a dependency.** `extraction.ObligationExtractor` is a `Protocol` with
one method — `extract(chunk_text, *, section_path) -> list[ExtractedObligation]` — and one
attribute, `adapter_id`. `LocalExtractor` speaks to an Ollama-compatible HTTP endpoint;
`NullExtractor` extracts nothing. `build_extractor(settings)` resolves the configured name and
**raises on an unknown one**, so a typo in `EXTRACTOR_ADAPTER` fails at startup rather than
halfway through ingesting a document, having already written a document's worth of nodes.

**The default adapter runs no model at all.** `extractor_adapter` defaults to `"null"`. A test
suite that cannot run without a GPU, a model download, or an API key stops being run — and the
whole value of the ratchet below depends on the suite being something a developer runs by
reflex. A fresh clone passes `uv run pytest` with no model server anywhere.

**Schema validation lives in our code, on every adapter.** `ExtractedObligation` is a Pydantic
model, and `LocalExtractor` validates every element of every response against it before
returning — a response that fails raises rather than being coerced, dropped, or partially
accepted. A hosted provider's JSON-schema mode and a local runtime's grammar are requested where
they exist (`"format": "json"` is sent to the local endpoint) but they are **optimisations behind
this boundary, never the boundary itself**. This is the specific property that makes a swap
behaviour-preserving: two adapters differ in how often they satisfy the contract, never in what
the contract is.

**`modality` is a closed enum, and its accuracy is pinned separately.** `SHALL | MUST | SHOULD |
MAY`. An adapter that invents `WILL` fails validation loudly instead of writing a value nothing
downstream can interpret. And `modality_accuracy` is a ratchet leg of its own, computed **only
over matched pairs**, because it answers a question no aggregate can: having correctly found the
duty, did we get its force right? A `SHALL` recorded as a `SHOULD` downgrades a binding
obligation to advice while scoring perfectly on precision and recall. In a compliance tool that
is the single most damaging error available, and an F1 absorbs it without trace.

**Confidence is recorded and never used to filter.** `write_obligations` stores whatever the
adapter reported, including 0.01. Phase 4's review queue decides what a human sees. An extractor
that silently dropped its own low-confidence output would hide precisely the cases a reviewer
most needs to look at, and would make its own failure rate invisible to the ratchet.

**Obligation identity is `hash(version_id, section_path, normalize(statement))`.** `normalize`
collapses whitespace and case-folds, and does nothing else. A reflowed line or a changed indent
must not orphan a human decision attached in Phase 4; a changed *word* must, because that is a
different obligation and Phase 5's edition diff needs to see it as one. The write is
authoritative (`SET`, not `ON CREATE SET`) for the same reason `write_chunks` is: identity
ignores case, so a re-extraction can reach an existing id carrying a different modality, and a
store whose entire purpose is to say how binding a duty is must answer with the current reading
rather than the first one ever recorded.

**Obligations hang off the version and anchor to the chunk.**
`(:DocumentVersion)-[:MANDATES]->(:Obligation)-[:ANCHORED_IN]->(:Chunk)`. The write requires the
chunk to belong to *that* version and raises `UnknownAnchorError` when it does not — an
obligation anchored in another edition's chunk would cite a passage the version does not contain,
and a silent no-match would report success having written nothing, which is the failure
`write_chunks` already learned to refuse. `:Obligation` is derived exactly as `:Chunk` is:
droppable by `drop_obligations`, rebuildable, never hand-edited.

**Extraction is cached on content, not on chunk id.** The design spec specified
`(chunk_content_hash, adapter_id, prompt_version)` and this phase's plan later paraphrased it as
`(chunk_id, adapter_id, prompt_version)`. The spec is right and the paraphrase is a bug. A chunk
id is a hash of *where* a chunk sits in the document's structure and deliberately not of its text
(ADR-012), precisely so that an unrelated edit does not move it — which means an edited edition
re-ingested under the same version reaches existing chunk ids carrying different words. Keyed on
the id, the cache would answer that chunk from text that no longer exists, invisibly and
indefinitely. `cache_key` therefore hashes the chunk's text together with its `section_path`,
which is rendered into the prompt and so also varies the answer, and prefixes the adapter id and
prompt version. `CachedExtractor` treats an empty result as a hit (`is not None`, not a truth
test) because most passages contain no obligation and treating that as a miss would re-run the
model over an entire document on every rebuild, for nothing. The store is
`:ExtractionCache` in the graph rather than a process-local dict, so a rebuild after a restart is
still cheap, under a uniqueness constraint so a concurrent ingest cannot leave two rows under one
key for the reader to choose between arbitrarily.

**A prompt change is a `PROMPT_VERSION` bump, never an in-place edit.** An in-place edit leaves
the cache serving results produced by a prompt that no longer exists anywhere — nothing reports
it, and the results look entirely normal.

**The ratchet is the swap gate.** `tests/test_obligation_ratchet.py` scores the configured
adapter against three hand-labelled passages drawn from `data/samples/`, following the pattern
`test_extraction_ratchet.py` established for the citation parser. Floors are recorded per
adapter and may only be raised. Matching is on `normalize(statement)` — the same form identity is
computed over, which is a deliberately hard bar: a paraphrase does not match. It has to be,
because a paraphrase produces a different `obligation_id`, and an extractor whose ids move on
every run cannot carry a human decision across a rebuild no matter how good its prose.

**The gold set is three shapes, chosen for what each can catch alone.** One passage dense in
duties (DoDD 5000.01 (2003) §4.3.4, four `SHALL`s) measures recall. One whose correct answer is
**empty** (DoDI 5000.88 §1.1, an applicability clause) measures precision, and is the only
fixture that can catch an extractor manufacturing a duty to seem useful. One mixing `MUST` and
`SHOULD` against two `may`s used as prediction rather than permission (DoDM 8180.01 §4) measures
modality and the discrimination a rules engine cannot make. Every gold statement is a verbatim
quotation of its passage, enforced by `test_the_gold_set_is_well_formed` — a paraphrased label
would make the recall floor unreachable by construction, and the tempting fix for an unreachable
floor is to lower it. `test_the_gate_has_teeth` runs a deliberately bad extractor against the
same fixtures and asserts it fails the local adapter's floors, so the gate cannot be vacuously
green.

**A gate that did not run says so.** The ratchet skips when the configured adapter has no floors
recorded, and when its model server is unreachable — and both skip messages open with `THE
EXTRACTION GATE DID NOT RUN`, because the default outcome on a developer machine with no model
running is a skip, and a green suite must never be mistaken for a passed gate.

**The deterministic citation extractor is untouched.** SPEC-001 requires it to stay model-free.
Obligation extraction is an additive second path over stored text, not a replacement.

## Consequences

**Makes easy.** Phase 4 can attach human review decisions to an `:Obligation` and expect them to
survive a re-extraction, because identity is content-derived and stable. Comparing two adapters
is a single command with a settings change and no code edit, and the comparison is like-for-like
because both are cached under keys that distinguish them. Adding a hosted adapter is one file
implementing one method plus a floors entry; nothing else in the codebase learns that a second
provider exists.

**Makes hard.** The exact-quotation matching bar means a good extractor that paraphrases scores
zero, so prompt work has to push the model toward quoting rather than summarising — which is the
right pressure for a citation tool, but it is a real constraint on prompt design, and it will
make the first measured floors lower than they would be under fuzzy matching. Extending the gold
set is manual labour that cannot be delegated to a model: a gold set derived from an extractor's
output cannot measure that extractor, so three fixtures and six obligations is a small sample
that only grows by someone reading policy text.

**Known limitation: the modality enum cannot represent `will`, which is how this corpus actually
writes binding duties.** Counted across the seven sample PDFs, `will` appears 458 times against
`may` 228, `must` 187, `shall` 93 and `should` 72 — and the distribution is generational, not
incidental. `500001p_2003.pdf` uses `shall` 92 times and `must` never; the 2020 re-issue of the
same directive (`500001p_2020.pdf`, also DoDD 5000.01) uses `shall` zero times, `must` 12 and
`will` 44. DoD's plain-language drafting style replaced the directive `shall` with `will`, so
`shall` is entirely absent from five of the seven samples and appears exactly once in a sixth —
which means an extractor faithfully following this ADR's closed enum can only report the minority
of those documents' duties. The enum is kept closed for this phase because a `SHALL`/`SHOULD`
confusion is the error that matters most and an open vocabulary makes it unmeasurable — but the
consequence is that the gold set has to draw its dense fixture from the 2003 directive, the one
sample whose vocabulary the schema fully covers. Widening the enum to include `WILL`, with its
own ratchet leg, is the first thing Phase 4 should consider; until then the recall this gate
reports is recall over `SHALL|MUST|SHOULD|MAY` duties, not over duties.

**Known limitation: the local adapter's floors are targets, not measurements.** No model server
was available when this phase landed, so `local:qwen3:8b`'s floors (precision 0.60, recall 0.50,
modality accuracy 0.85) are the plan's initial estimates and have never been scored against the
gold set. They are recorded so the gate has something to enforce the moment a model is pointed at
it. The ratchet-up rule applies from the **first measured run**: that run replaces these
estimates with what was actually observed, in either direction, and every run after it may only
raise them.

**Commits us to.** Validation living in our code on every adapter, permanently — the moment a
provider's own schema mode is treated as sufficient for that provider, the two adapters no longer
implement the same contract and the ratchet's per-adapter comparison stops meaning anything.
It also commits the project to maintaining a hand-labelled gold set as a first-class artefact:
it is the only thing standing between "we swapped the model" and "we swapped the model and the
graph is now subtly wrong", and it decays as the corpus grows unless someone keeps labelling.
