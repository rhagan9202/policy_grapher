# ADR-037: The model is constrained by the schema

**Status:** Accepted · **Date:** 2026-08-31 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

Every local extraction call has, until this sprint, asked Ollama for `"format": "json"` —
the legacy mode that guarantees the response parses as JSON and enforces nothing about its
shape. `validate_extracted` catches everything else, after the fact: a wrong enum member, a
missing field, a statement that never contains its own modality word. That worked, but it
worked by discarding the model's output once it was already wrong, not by making the wrong
output unreachable.

Three measured costs of the free-form mode, from this project's own history:

- **`modality: null` losing 8 chunks in 37** (2026-08-26, ADR-030's own measurement). One
  sentence the model could not classify discarded every obligation that shared its chunk;
  ADR-030 later moved the cost from the chunk to the item, but the model was still free to
  emit `null` in the first place.
- **The sprint 11 repetition loop.** `will_dense`'s output carried 25 `statement` fields
  and 6 distinct values — the model found the right answers and then repeated two of them
  ten times each until `num_predict` cut it off, corrupting the JSON and rejecting the whole
  chunk (commit `944130d`). A generation cap bounded the cost; it did not stop the model from
  writing a shape nothing downstream wanted.
- **The `"model output was not JSON"` rejection branch** in `LocalExtractor` — the
  fallback for a response that fails to parse at all, whether from truncation, a stray
  token, or the model wandering off the requested shape. Every one of those is a chunk
  priced at its full cost under ADR-023/ADR-030, for a failure mode a constrained decoder
  is specifically built to make unreachable.

Ollama can instead be handed the actual JSON Schema for `ExtractionPayload` and mask any
token that would violate it — invalid enum values, missing required fields, and malformed
JSON become unemittable rather than caught downstream. Tasks 1–3 of this sprint wired that
in behind `Settings.extractor_decoding` (`"schema"` | `"json"`), made it part of the cache
key so the two modes never share answers, and verified against the live server (Ollama
0.32.15) that it accepts `ExtractionPayload`'s `$defs`/`$ref` nesting unmodified — no schema
flattening was needed. `"json"` was kept reachable rather than deleted, because a hosted
adapter may not support constrained decoding at all and the two need to stay comparable.

This ADR is the measurement that decides between them.

## Options considered

**Keep `"json"` as the only mode.** Simplest, and the status quo. Leaves the three costs
above unaddressed by construction — they are all instances of the model writing something
outside the shape we need, which is exactly what `"json"` cannot prevent.

**Make `"schema"` the only mode, and delete `"json"`.** Removes a mode this task exists to
measure, and forecloses ever running against a hosted adapter that cannot constrain — the
switch is retained by Tasks 1–3 for exactly that reason. Rejected for now, not ruled out
permanently.

**Default to `"schema"`, keep `"json"` as a fallback switch.** What Tasks 1–3 already built.
Evaluated below.

## Decision

**`"schema"` is the default. `"json"` is retained as a switch**, selected by
`EXTRACTOR_DECODING=json` or `Settings(extractor_decoding="json")`, because a hosted adapter
in a later ADR may not offer constrained decoding and the project needs the two modes to
stay comparable rather than have the code path disappear the moment it is not the default.

## The measurement

One variable moved: `EXTRACTOR_DECODING`. Same model (`llama3.1:8b`, Ollama 0.32.15, CPU),
same prompt (`PROMPT_VERSION 4`), same eight-fixture / twenty-eight-obligation gold set,
same runtime. Two separate processes per mode, per this project's standing rule that
repeated runs *inside* one process have previously proven less than they appeared to
(`test_obligation_ratchet.py`'s own history records 0.842 and 0.905 for the same build in
two processes on 2026-08-27). Never run concurrently — Ollama serialises.

```bash
cd backend
EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b EXTRACTOR_DECODING=json \
  uv run pytest tests/test_obligation_ratchet.py::test_the_configured_extractor_clears_its_floors -v -rs

EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b EXTRACTOR_DECODING=schema \
  uv run pytest tests/test_obligation_ratchet.py::test_the_configured_extractor_clears_its_floors -v -rs
```

| Mode | Process | Precision | Recall | Modality accuracy | Matched / Predicted / Gold |
| --- | --- | --- | --- | --- | --- |
| `json` | 1 | 0.862069 | 0.892857 | 1.000 | 25 / 29 / 28 |
| `json` | 2 | 0.862069 | 0.892857 | 1.000 | 25 / 29 / 28 |
| `schema` | 1 | 0.862069 | 0.892857 | 1.000 | 25 / 29 / 28 |
| `schema` | 2 | 0.862069 | 0.892857 | 1.000 | 25 / 29 / 28 |

All four runs agree bit-for-bit. Neither mode scored lower than the other on any leg — there
is no regression to report and no gain to claim from the number alone.

**That agreement was checked, not assumed.** Identical scores to the fourth decimal across a
mode switch is exactly the shape a wiring bug produces — the cache key covering the decoding
mode, in particular, is new this sprint and a defect there would silently serve one mode's
answers under the other's label. Verified directly: `LocalExtractor._post_with_retries` was
called by hand for both modes against one fixture (`shall_dense_dodd_5000_01_4_3_4.json`),
bypassing any cache, and the raw `/api/generate` request bodies carried different `format`
payloads (the full JSON Schema versus the bare string `"json"`) while the raw response
bodies came back byte-identical. The model, at temperature 0, already writes output the
free-form mode's own downstream validator accepts on every gold fixture — so on *this* gold
set neither mode has an opportunity to diverge. That is a property of the gold set's current
coverage, not a general claim that the constraint is inert; see Consequences.

## Consequences

**The floors do not move.** `test_obligation_ratchet.py`'s `FLOORS["local:llama3.1:8b"]`
stays at `{"precision": 0.862, "recall": 0.892, "modality_accuracy": 0.85}`. The lower
schema-mode observation truncates to precision 0.862 and recall 0.892 — the values already
recorded, not higher ones, so there is nothing to ratchet up to. Modality accuracy is
observed at 1.000 in both processes and both modes, and is deliberately left at 0.85 for the
reason already on record in that file: over a handful of matched pairs, a floor set at the
ceiling fires on the first single wrong answer, and that argument holds regardless of which
decoding mode produced the ceiling.

**An honest reading of a tie.** The literature's usual finding is a constraint tax — grammar-
masked decoding can cost accuracy on tasks where the "natural" token is outside the allowed
set. Nothing here contradicts that; nothing here confirms it either. This gold set's eight
fixtures do not currently contain a chunk where `llama3.1:8b` wants to write something the
schema forbids, so the measurement is a true tie, not a small win rounded up into one. A
result presented as a clean improvement would misrepresent what was actually observed.

**Chosen anyway, on reasoning the gold set cannot exercise.** The three costs in Context —
the null-modality chunks, the repetition loop, the raw JSON-parse rejection — are each a
case of the model writing outside the shape needed, and none of the eight gold fixtures
happens to trigger one under the current prompt (`PROMPT_VERSION 4`) and generation cap
(2048 tokens). Constrained decoding makes each of those shapes structurally unreachable
rather than merely rare, which is a claim about the *space* of possible outputs, not the
eight samples drawn from it. The gold set proves the two modes tie on what has already been
observed; it cannot prove the tie holds under a chunk this prompt has not yet produced. That
gap is the honest reason for choosing `"schema"` as the default rather than treating this
measurement as decisive on its own.

**What this makes easy.** Any future gold fixture that exercises one of the three costs
above turns from a shared failure into a `schema`-only pass, without anyone having to notice
and fix a prompt regression by hand first — the constraint is enforced by the server, not by
a rule someone has to remember to keep true.

**What it commits us to.** `"json"` has to keep working and keep being measured, not just
compile — the day a hosted adapter is added under a later ADR, this same table is what tells
whether it can run in `"schema"` mode at all, and if it cannot, whether its `"json"` numbers
clear the floors on their own.

## Relationship to ADR-030

ADR-030 priced the cost of an item a chunk's other items should not have to pay for. The
class of item it was written against — one sentence the model could not classify, discarded
alongside obligations that had nothing wrong with them — mostly stops existing under
`"schema"`: `modality: null` and a missing required field are now unemittable rather than
merely invalid.

**ADR-030 is not superseded.** It still governs whatever the Python-level validators refuse
after a syntactically valid response comes back — most concretely, the rule that a
`statement` must contain the modality word it is labelled with. No JSON Schema can express
"this string must contain that other field's value"; `Modality` being a closed enum is
schema-expressible, but the cross-field containment check is not, and stays a
`validate_extracted` rule enforced after generation, subject to ADR-030's per-item cost
exactly as before.
