# Research: architecture and workflow gaps

**Date:** 2026-08-31 · *Dated record — a snapshot of what was found, not a living document.*

Research into the codebase, the documentation, and current published practice, to inform
where this project should spend its next few sprints. Four findings, ordered by value per
unit of work. Two are small changes with large blast radius; two are process gaps.

Nothing here is a decision. Where a finding implies one, it names the ADR that would record it.

## What was examined

The extraction pipeline (`extraction/`, `chunking.py`, `chunks.py`), the two ratchet suites,
the CI workflow, retrieval fusion, and the config defaults. On the documentation side: the
vision, roadmap, backlog, architecture, conventions, and the sprint 9–11 retrospectives.
External practice was researched for four specific problems this project already has, rather
than surveyed generally — sources are linked inline.

## Finding 1 — The extractor asks the model for JSON, not for its schema

**This is the highest-value change available and it is roughly five lines.**

[`local.py:74`](../../../backend/src/policy_grapher/extraction/local.py#L74) sends
`"format": "json"` to Ollama. That is the **legacy JSON mode**: it constrains decoding only
far enough to guarantee the output parses. It does not enforce field names, types, or enum
values — any syntactically valid JSON satisfies it.

Ollama has accepted a **JSON Schema object** in the same `format` field since 0.3.0. That
path compiles the schema to a state machine and zeroes the logit of any token that would
violate it, at every step. Field names, types and **enum membership** are then structurally
impossible to violate rather than checked afterwards.

The project is currently paying for that difference in three measured places:

| Measured defect | Where recorded | What schema-constrained decoding does to it |
| --- | --- | --- |
| `modality: null` on scope sentences cost **8 chunks in 37**, lost whole | [`local.py`](../../../backend/src/policy_grapher/extraction/local.py) comment, measured 2026-08-26 | `Modality` is a closed enum; null becomes unemittable |
| Repetition loop — **25 statements, 6 distinct**, invalid JSON | [sprint 11 retrospective](../../sprints/sprint-11/retrospective.md) | `maxItems` bounds the array structurally |
| `"model output was not JSON"` rejection branch | [`local.py`](../../../backend/src/policy_grapher/extraction/local.py) | The class is eliminated, not handled |

The `ExtractedObligation` Pydantic model already exists, so the schema is
`model_json_schema()` — no new artifact to maintain, and it cannot drift from validation
because it *is* the validator.

**The caveat is real and must be measured, not assumed.** Constrained decoding carries a
documented "constraint tax" — forcing the grammar can shift output quality, and at least one
2026 study measures capability suppression under structured-output constraints. So this is an
experiment with a pass/fail, not a refactor. This project is unusually well equipped to run
it: the gold set and floors in
[`test_obligation_ratchet.py`](../../../backend/tests/test_obligation_ratchet.py) answer the
question directly, and the sprint 10 action *change one thing when a number will be read from
it* is exactly the discipline it needs.

The capability is available: `docker-compose.yml` runs `ollama/ollama:latest`, comfortably
past the 0.3.0 that introduced schema-constrained `format`.

A decision this shape warrants an ADR: *the model is constrained by the schema, not asked for
it*. It also partly supersedes the reasoning behind
[ADR-030](../../specs/adr/ADR-030-a-rejected-item-costs-itself-not-its-chunk.md), which
allocates the cost of items the schema refuses — a class that mostly stops existing.

### 1b — The model runtime is unpinned, and every floor is measured against it

Checking the above surfaced a separate problem. `docker-compose.yml:254` and `:274` both run
`ollama/ollama:latest`.

This project pinned `neo4j:2025.10` deliberately, and
[architecture.md](../../specs/architecture.md) records why: "`latest` would make the database
version depend on when it was last pulled." That reasoning applies with **more** force to the
model runtime than to the database. Ollama's version determines sampling, decoding, and
default options — the machinery that produces the numbers in `FLOORS`. An unpinned runtime
means extraction behaviour can change with no commit, no `PROMPT_VERSION` bump, and no cache
invalidation, because the cache key holds `adapter_id` and `prompt_version` but nothing about
the runtime that served them.

That is the same class of defect sprint 12 exists to detect — a change with non-local effects
that nothing reports — arriving through the one door the blast-radius work would not watch.
It also quietly weakens the ratchet file's most careful reasoning: the precision floor was set
to 0.842 rather than 0.905 to absorb variation *between processes*. Variation between runtime
versions is not bounded at all.

Two candidate fixes, and they compose: pin the image to a version, and add the runtime version
to the cache key or at minimum record it beside each floor measurement. The first is one line
and is consistent with a decision this project has already taken once.

## Finding 2 — The extraction gate has never run in CI

`test_the_configured_extractor_clears_its_floors` is the gate on the product's core value.
It does not run in continuous integration, and cannot currently.

The chain, verified rather than inferred:

- `Settings.extractor_adapter` defaults to `"null"`
  ([`config.py:52`](../../../backend/src/policy_grapher/config.py#L52))
- the null adapter's `adapter_id` is `"null"`
  ([`null.py:13`](../../../backend/src/policy_grapher/extraction/null.py#L13))
- `FLOORS` holds exactly one key, `"local:llama3.1:8b"`
  ([`test_obligation_ratchet.py:163`](../../../backend/tests/test_obligation_ratchet.py#L163))
- so `FLOORS.get("null")` is `None`, and the test takes its **first** skip branch — it never
  reaches the model-reachability check
- `.github/workflows/ci.yml` declares no `services:` and no model server; its only mention of
  ollama is an image-size assertion

The skip is loud, honest, and says exactly what it means. That is not the problem. The
problem is that this project's own stated principle — *a skip nobody reads is how a check
dies* — is applied in the same CI file to torch, where the dev extra is installed
deliberately so that "two tests that can only be demonstrated by a real model" do not skip.
The identical reasoning has not been extended to the extraction model, which guards
considerably more.

This compounds Finding 3: three sprints running, a prompt edit degraded an unrelated passage,
and the gate that would have caught it was green-by-skip on every push.

Options, cheapest first — the choice is a real trade and belongs to the owner:

1. **Record floors for the `null` adapter.** Rejected once already, on good grounds: the
   ratchet file's own history says removing `FLOORS["null"]` was what stopped the gate being
   vacuous. Do not re-introduce it.
2. **Fail rather than skip when the adapter is one CI was expected to exercise.** Turns the
   silent-by-default case into a decision someone has to make.
3. **Run a model in CI.** An 8.43GB image against GitHub-hosted runners is slow and probably
   the wrong trade for every push; a nightly or release-branch job is the shape the eval
   literature recommends for the expensive tier.
4. **Run the gate against a smaller US-origin model** (`llama3.2:3b` is already in
   `US_ORIGIN_MODELS`) with its own floors, so *something* model-bound runs per push.

## Finding 3 — STORY-107 has an established shape, and a name

[STORY-107](../../backlog/stories/STORY-107-a-prompt-change-shows-its-blast-radius.md) asks
for "a differential check over real chunks, needing no labels: record what the prompt
produces, report what moved," and records that the decision *is* the work. Published practice
has converged on this pattern and calls it **canary replay**: a versioned, hashed, dated set
of 50–200 inputs, replayed against a fixed model id, compared against a recorded day-one
baseline. It needs no ground truth because it does not ask whether output is *right* — only
whether it *moved*, and where.

That maps onto this repo almost directly, and the pieces already exist:

- **The corpus is the canary set.** `data/samples` holds seven PDFs; one document measured 37
  chunks, so 50–200 chunks is the natural size rather than an arbitrary one.
- **Replay is already cheap.** The extraction cache keys on
  `(chunk_text, section_path, adapter_id, prompt_version)`
  ([`cache.py`](../../../backend/src/policy_grapher/extraction/cache.py)), so a baseline at
  `PROMPT_VERSION = 4` is a cache the next version is diffed against. The versioning
  discipline this needs is already enforced.
- **What to record** is what `score()` already computes per passage, minus the gold
  comparison: counts, modalities, and normalised statements. A moved statement is a diff line.

The layering the eval literature recommends fits the two suites this project already has:
keep the labelled gold set small and fast as the **correctness** gate (does it still get the
right answer?), and add the unlabelled canary set as the **blast-radius** gate (did anything
else change?). The gold set answers sprint 9's failure; only the canary set answers sprints
9, 10 and 11's *shared* failure.

**Note the interaction with Finding 1.** Schema-constrained decoding removes two of the three
historical blast-radius symptoms — the loop and the invalid JSON — but not the third. Sprint
9's regression was a fixture going 5 of 5 to 0 with valid, schema-conforming output. The
canary set is still needed; constrained decoding shrinks what it has to catch.

## Finding 4 — Standing actions have no living home

Sprints 9–11 produced roughly eight actions marked **Standing** — an anomaly is a hypothesis
about the measurement first; change one thing when a number will be read; mutate by keeping a
copy; one model-bound job at a time; verify a denominator before quoting a ratio; a floor is
truncated, never rounded.

Every one of them lives only in a retrospective, which
[CONVENTIONS](../../CONVENTIONS.md) correctly freezes and forbids editing. So a standing rule
is discoverable only by reading three dated documents and knowing which supersede each other
— and sprint 11 found exactly that failure mode, writing that *a standing action is a
measurement's descendant and inherits its errors* after discovering the determinism
conclusion it had been applying for a sprint was drawn from two different builds.

`AGENTS.md` has a **Standing rules** section, but it holds two owner-set rules and reads as
the owner's, not as an accumulating working agreement.

The gap is structural, not a matter of diligence: a rule that must be re-derived from frozen
records will be applied inconsistently, and a wrong one has no home to be corrected in. The
fix is a living document — the retrospective still records *when and why* a rule was adopted,
and the living document holds the current set. That preserves one-fact-one-home: the
retrospective owns the history, the living doc owns the present.

## What is already right — do not change it

Worth stating explicitly, because a research note that only lists gaps misrepresents the
system.

- **Retrieval fusion is current best practice.** `retrieval/hybrid.py` uses reciprocal rank
  fusion with `RRF_K = 60`, the original paper's value, recorded as a visible decision. RRF is
  what the 2026 GraphRAG literature recommends for exactly this reason — no score calibration
  needed between a vector leg and a full-text leg.
- **The scoring design is better than standard.** Pinning precision, recall and modality
  accuracy separately, refusing an aggregate F1 because it would absorb a SHALL read as a
  SHOULD, is the right call for a compliance tool and is not what most harnesses do.
  Micro-averaging over pooled counts rather than averaging rates is also correct, and the
  docstring says why.
- **Ratchets that cannot be silently bypassed.** `test_every_sample_pdf_is_ratcheted` with no
  exclusion list, and `test_the_gate_has_teeth` proving an inventing extractor fails the
  floors, are both guards against vacuous gates — the failure class this project has hit
  repeatedly and now systematically defends.
- **Cache keying on `PROMPT_VERSION`** with an in-place prompt edit treated as a bug. This is
  what makes Finding 3 cheap.
- **Separating the decision from the mechanism.** Sprint 9 recorded that ADR-033 was wrong
  about the mechanism and that this cost nothing, because the decision was recorded apart from
  it. That is a real architectural property of the documentation, and it is working.

## Suggested sequencing

Finding 1 before Finding 3, because constrained decoding changes what the canary baseline
should be recorded against — establishing a baseline and then invalidating it a sprint later
repeats the sprint 10 action *order rule changes before the long job they invalidate*.

0. **Finding 1b** — pin `ollama/ollama`. One line, and it must come first: every measurement
   below is taken against that runtime, and pinning afterwards pins an unknown.
1. **Finding 1** — measure schema-constrained decoding against the gold set. One variable, one
   number, ADR either way.
2. **Finding 3** — record the canary baseline at whatever `PROMPT_VERSION` that lands as.
3. **Finding 2** — decide what CI does about the gate; cheapest option is a decision, not code.
4. **Finding 4** — a living document, ten minutes, no code.

## Sources

- [Ollama — Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama blog — Structured outputs](https://ollama.com/blog/structured-outputs)
- [Generating Structured Outputs from Language Models: Benchmark and Studies](https://arxiv.org/html/2501.10868v1)
- [Constraint Tax in Open-Weight LLMs](https://arxiv.org/pdf/2606.25605)
- [Langfuse — LLM regression testing](https://langfuse.com/resources/engineering/llm-regression-testing)
- [Braintrust — LLM evaluation guide](https://www.braintrust.dev/articles/llm-evaluation-guide)
- [LLM Readiness Harness: Evaluation, Observability, and CI Gates](https://arxiv.org/pdf/2603.27355)
- [LLM monitoring and drift detection — canary replay](https://leanware.co/insights/llm-monitoring-drift-detection-guide)
- [Towards Practical GraphRAG: Efficient Knowledge Graph Construction and Hybrid Retrieval](https://arxiv.org/pdf/2507.03226)
