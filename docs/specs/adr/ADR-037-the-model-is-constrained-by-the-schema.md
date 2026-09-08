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
repeated runs *inside* one process prove less than they appear to. That rule survived a
correction: sprint 9 (2026-08-28) measured precision 0.842 and then 0.905 for the same gold
set in two processes on the same day and, at the time, read that as evidence two processes
can disagree. Sprint 11 (2026-08-30) found the real cause — those two measurements ran
against *different builds*, before and after ADR-035's actor rule landed, not two processes
of one build — and re-measured properly: **identical scores across six runs in two separate
processes** of one build. That re-measurement, not the sprint 9 number, is the standing
evidence that two processes of the same build agree, and it is why two processes per mode is
still the right amount of rigor here rather than one. Never run concurrently — Ollama
serialises.

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

**That agreement was checked, not assumed.** Identical scores to the sixth decimal across a
mode switch is exactly the shape a wiring bug produces — the cache key covering the decoding
mode, in particular, is new this sprint and a defect there would silently serve one mode's
answers under the other's label. Verified directly: `LocalExtractor._post_with_retries` was
called by hand for both modes against one fixture (`shall_dense_dodd_5000_01_4_3_4.json`),
bypassing any cache. The raw `/api/generate` request bodies carried different `format`
payloads (the full JSON Schema versus the bare string `"json"`), and the `response` *text*
of the two replies — the model's generated JSON, not the enclosing envelope, which also
carries per-call fields like `total_duration` and `eval_count` that are never expected to
match — was compared for full string equality (and cross-checked with a SHA-256 hash of
each) and came back identical, not merely a matching length or prefix. The model, at
temperature 0, already writes output the free-form mode's own downstream validator accepts
on every gold fixture — so on *this* gold set neither mode has an opportunity to diverge.
That is a property of the gold set's current coverage, not a general claim that the
constraint is inert; see Consequences.

**That the constraint is actually enforced, not merely accepted, was checked separately.**
Getting a 200 and a well-shaped payload back (verified when `"schema"` mode was implemented,
against Ollama 0.32.15) proves the server accepts the schema; it does not prove the server
masks tokens against it, because a server that silently ignored an object `format` and just
happened to produce a schema-conforming answer would return the exact same response. The
discriminating test: take `ExtractionPayload`'s generated schema, narrow `Modality`'s `enum`
from all six members to `["WILL"]` alone, and send it against the `shall_dense` fixture —
whose gold obligations are all naturally `SHALL` and contain the word "shall" in every
statement. Under the real schema the model returns three `SHALL` obligations, as expected.
Under the hostile schema it returns four obligations (one more is admitted once "shall...
serve as control objectives" is treated as a duty rather than dropped), and **every one is
labelled `"WILL"`** — including the ones whose `statement` text still reads "PMs shall
manage programs..." verbatim, with the word "shall" left untouched in the string and only
the `modality` field forced to the sole enum member the hostile schema permitted. A server
that was not enforcing the schema had no reason to change the label at all. This is direct
evidence that constrained decoding binds on this server and model, not merely that it
parses. Full request/response evidence is in the task report.

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
after a syntactically valid response comes back. The rule that a `statement` must contain
the modality word it is labelled with is *not* the right example of that — because
`Modality` is a closed enum, the check is enumerable as a JSON Schema after all (an `anyOf`
of five branches, each pairing `modality: {"const": "SHALL"}` with a `statement` `pattern`
requiring the word, and so on for each word modality), and a future iteration could move it
into the schema if it were worth the schema's added size.

What stays outside any schema, structurally, is a rule that needs information the model's
output object does not carry. `ExtractionPayload` is built from `obligations: list[ExtractedObligation]`
alone — no `section_title`, no `chunk_text` — so two rules this project already enforces in
Python cannot be expressed under any encoding, no matter how the schema is written:

- **ADR-033's section guard**, which permits `ASSIGNED` only in a chunk whose `section_title`
  names a responsibilities section. `section_title` is an argument to `extract()`, not a
  field the model emits, so no constraint on the emitted JSON can reference it.
- **ADR-034's quotation rule**, that a `statement` must occur verbatim in the `chunk_text` it
  was read from. The passage is the prompt, not the schema, and JSON Schema validates a
  document against itself — it has no mechanism to check one field against text that was
  never part of the instance being validated.

Both remain `validate_extracted` rules enforced after generation, subject to ADR-030's
per-item cost exactly as before.
