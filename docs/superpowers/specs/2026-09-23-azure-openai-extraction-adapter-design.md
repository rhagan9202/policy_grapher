# An Azure OpenAI extraction adapter, for closed development

**Status:** Design (rev. 3) · **Date:** 2026-09-23 ·
**Suspends, while ADR-043 is in force:** U3, U4, U5 and U6 of
`docs/plans/2026-09-22-1130-feat-two-adapters-ingestion-and-managed-extraction-plan.md`. The
ingestion half of that plan (U1, U2, U7, U8) is untouched.

> **Rev. 2** answers an adversarial review of rev. 1, which found three blocking errors, all
> confirmed against the code. First, rev. 1 claimed `uv run pytest` spends nothing with `azure`
> configured, but `test_responsibilities_coverage.py:119-139` extracts a whole section through
> any non-null adapter (§2). Second, it said U3 and U4 "still stand", although either one as
> written turns the suite red for exactly the adapter this relaxes (header, §2). Third, it
> configured an adapter the compose stack could never see: `docker-compose.yml` lists its
> environment explicitly and has no `env_file` (§3.6). It also found material errors: an
> exhausted throttle was being turned into lost obligations (§3.4), refusals would crash, and
> the strict-schema keywords were left unnamed (§3.2). Those are corrected here too.
>
> **Rev. 3** follows from the project owner naming the deployments actually available: gpt-4o,
> gpt-5.1 and gpt-5.6-luna. Two of the three are reasoning models, which reject both
> `temperature` and `max_tokens`, the two parameters rev. 2 sent on every request. The request
> shape is now chosen by a setting (§3.1), the output cap is the adapter's own (§3.6), and the
> reasoning effort joins the cache variant (§3.3). Every reasoning-model claim here comes from
> learn.microsoft.com/azure/ai-foundry/openai/how-to/reasoning, as updated 2026-09-21.
>
> **Amended after the final branch review.** A served-model mismatch now ends the run instead of
> costing its chunk (§3.3, §3.4), because a retargeted deployment answers every chunk that way. A
> refusal carries Azure's own `error.code` and `error.message` (§3.4). Every malformed answer
> shape costs its chunk (§3.4). The endpoint check refuses a path, query, fragment or userinfo
> (§3.5). The model is not sent `ExtractionPayload`'s docstring (§3.2). "`pytest` does not spend"
> holds only while the Azure settings are in `.env` and not exported in the shell (§3.6, §7).

## 1. Goal

An operator with an Azure Government OpenAI deployment and its API key sets
`EXTRACTOR_ADAPTER=azure` plus the `AZURE_OPENAI_*` values (§3.6) and gets obligations extracted
through it, with no model on the operator's machine and no code change, both host-run and under
compose. A fresh clone and CI still run with no key (`null` default).

This settles the one question the two-adapter plan left open (which provider) with the project
owner's answer from this session: **Azure OpenAI, authenticated by API key, on Azure Government
(`*.azure.us`)**. Plain `api.openai.com` is not a target; "OpenAI" in the request meant the GPT
models Azure serves. The deployments available to the project are **gpt-4o, gpt-5.1 and
gpt-5.6-luna**, and all three are supported (§3.1).

## 2. What closed development changes, and how it is recorded

The project is in closed development and testing. The project owner directed that this adapter
ship **without** the hard gates the two-adapter plan designed for it:

- no accreditation record and no accreditation check at construction (plan KTD5, R7);
- no US-origin set entry for the served GPT model (ADR-020, `US_ORIGIN_MODELS` at
  `backend/tests/test_obligation_ratchet.py:33`);
- no recorded floors, and no gate that fails for want of them (plan U3, U6).

The repo's rule is that where a plan and an ADR disagree, the ADR wins. ADR-041 ("an adapter
that cannot name its accreditation is an unaccredited adapter") and ADR-020 both bind this
adapter as written, so code without these gates would contradict accepted decisions. The
relaxation is therefore **recorded as ADR-043** (§6).

What the suite does today with `EXTRACTOR_ADAPTER=azure` in `.env`, traced against the code:

- **`test_the_configured_extractor_clears_its_floors`** (`test_obligation_ratchet.py:321-330`)
  skips when `FLOORS` has no entry for the adapter. It calls `build_extractor(Settings())` *before*
  the skip, so an incomplete `azure` configuration errors the test instead of skipping it. That is
  correct: a misconfigured adapter should be loud. With a complete configuration it skips, and
  makes no call.
- **`test_the_shipped_model_has_recorded_floors`** uses `Settings(_env_file=None,
  extractor_adapter="local")`, and **`test_the_default_extraction_model_is_us_origin`** uses
  `Settings(_env_file=None)` (`test_obligation_ratchet.py:378-401`). Neither reads `.env`, and the
  Azure model lives in its own setting, never in `extractor_model`.
- **`test_enough_of_the_responsibilities_section_is_read`**
  (`test_responsibilities_coverage.py:119-139`) skips only for `null`. With `azure` it would call
  Azure for every responsibilities chunk of DoDD 5000.01 on every run, because its `integration`
  marker is not deselected by `addopts`. It would also assert the 0.80 coverage floor against an
  unmeasured model. **This test changes:** it skips for any adapter with no entry in the
  ratchet's `FLOORS`, importing `FLOORS` from `test_obligation_ratchet` and giving a skip message
  in the same loud style ("THE COVERAGE FLOOR DID NOT RUN: … has no recorded floors"). One rule
  across both floors tests: an unmeasured adapter is not gated and is not spent on.

The plan units suspended while ADR-043 is in force:

- **U3** (floors gate fails rather than skips for a non-null adapter) would fail the suite for
  `azure`.
- **U4** (provenance and floors tests examine the configured adapter) would fail the US-origin
  check for a GPT model.
- **U5 and U6** are replaced by this spec.

All four return, as written, when ADR-043 ends.

## 3. The adapter

New module `backend/src/policy_grapher/extraction/azure_openai.py`, class
`AzureOpenAIExtractor`. It is a peer of `LocalExtractor`, not a parameterisation of it (plan
KTD4). It reuses `EXTRACTION_PROMPT`, `ExtractionPayload` and `validate_extracted`, so per-item
validation and dropping behave exactly as in `local.py` (ADR-030, ADR-033).

### 3.1 Transport

Plain `httpx`, as `local.py` uses; no `openai` SDK dependency.

- `POST {endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}`
- Header `api-key: <key>`.
- Body, common to both shapes below:
  - `messages`: one `user` message holding the formatted `EXTRACTION_PROMPT`, with the same
    `section_path` join as `local.py`.
  - `response_format` per §3.2.
- `transport: httpx.BaseTransport | None` and `backoff_seconds` are constructor parameters, as in
  `LocalExtractor.__init__`, so every test runs offline and without real sleeps. Timeout is
  `extractor_timeout_seconds`.

**Two request shapes, chosen by `azure_openai_reasoning_effort`, not by model name.**

| Setting | For | Sends | Omits |
| --- | --- | --- | --- |
| empty | gpt-4o | `temperature: 0`, `max_tokens: azure_openai_max_output_tokens` | `reasoning_effort` |
| set (`none`, `low`, `medium`, `high`, …) | gpt-5.1, gpt-5.6-luna | `max_completion_tokens: azure_openai_max_output_tokens`, `reasoning_effort` | `temperature` |

Why a setting rather than recognising the model:

- Reasoning models reject `temperature`, `top_p` and `max_tokens`, and accept only
  `max_completion_tokens` on Chat Completions.
- Which *effort* values a model accepts varies by model: `minimal` is refused from gpt-5.1 on,
  and `max` is Responses-API-only.
- A name table in the adapter would be wrong for the next deployment and silently choose for the
  operator.

The effort value is passed through unvalidated, so Azure is the authority on what a model accepts.
A mismatch between the setting and the model reaches Azure on the **first** chunk as a 400 naming
the parameter: an empty setting pointed at gpt-5.1 sends `temperature`, and a set one pointed at
gpt-4o sends `reasoning_effort`. §3.4 makes that 400 end the run at once, with Azure's message,
rather than after 204 chunks.

**Determinism.** gpt-4o runs at temperature 0. The reasoning models cannot be pinned, so repeated
uncached runs over the same chunk may differ. The extraction cache makes re-running an edition
stable. Measuring floors for a reasoning model later (the returning U6) will need repeated runs,
and that is recorded here so it is not rediscovered.

**Endpoint form.** The docs now lead with the v1 route (`/openai/v1/chat/completions`, deployment
named as `model` in the body, no `api-version`). This adapter keeps the deployment path with
`api-version`: the long-standing form, where the v1 route's availability on Azure Government
could not be confirmed from this machine. If the live check (§7)
finds a model reachable only on v1, switching is a URL-and-body change inside `_post_with_retries`,
recorded as a bug against this adapter.

### 3.2 Decoding

Reuses `extractor_decoding` (`config.py:60`):

- `schema` → `response_format: {"type": "json_schema", "json_schema": {"name":
  "obligations", "strict": true, "schema": STRICT_SCHEMA}}`.
- `json` → `response_format: {"type": "json_object"}`.

`STRICT_SCHEMA` is derived once at import from `ExtractionPayload.model_json_schema()`:

- Every object gets `additionalProperties: false`, and a `required` list of all its properties.
  The generated schema already lists all of them. The derivation sets the list from `properties`
  rather than trusting it, because strict mode requires every property listed; a nullable field
  stays nullable through its `anyOf`.
- `ExtractionPayload`'s top-level `description` (its docstring, a note to maintainers) is dropped
  so it is not sent on every billed call. `Modality`'s description stays, because it says what the
  enum's values mean.
- These keywords are removed wherever they appear: **`minLength`, `maxLength`, `minimum`,
  `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `pattern`, `format`**. They are Azure
  structured outputs' documented unsupported type-specific keywords, and `ExtractedObligation`
  carries the first four (`extraction/schema.py:71-77`).
- `$defs`/`$ref` and `anyOf` with `null` are supported and left alone.

Nothing is lost by stripping. Every item is still validated locally by `validate_extracted`,
which enforces the full model.

### 3.3 Identity

- `adapter_id = f"azure:{azure_openai_model}"`. `azure_openai_model` names the **model
  version** as Azure returns it (e.g. `gpt-4o-2024-08-06`), not the deployment name. It has to
  come from configuration because the cache key (`extraction/cache.py:45-56`) is built before
  any call.
- `cache_variant = f"{decoding}@{api_version}#{schema_digest}~{effort}"`.
  - `schema_digest` is the first 12 hex characters of the SHA-256 of `STRICT_SCHEMA`, serialised
    with sorted keys, or `"-"` in `json` mode. A change to the derivation therefore stops
    replaying answers produced under the old schema.
  - `effort` is `azure_openai_reasoning_effort`, or `"-"` when empty. An answer produced at `low`
    is never replayed as a `high` one.
  - The output cap is not in the variant: a cap changes whether an answer completes, not what a
    completed answer says, and a truncated answer is never cached (§3.4).
- Each response's `model` field is compared exactly to `azure_openai_model`. On a mismatch the
  adapter raises `ServedModelMismatch` (a `RuntimeError`, not a `ValueError`) naming both values,
  so an alias retargeted behind a stable deployment name cannot have its answers cached under the
  old model's id. It **ends the run** rather than costing the chunk: a retargeted deployment
  answers every chunk with the other model, so as a `ValueError` it would bill a whole edition
  and discard every answer. It is a configuration error, like a wrong key.
  - The comparison runs only on a cache miss. That is enough: the raise comes before the cache
    `put` (`cache.py:178-183`), so nothing wrong is written.
  - Azure returns the dated form, so exact comparison is right.

### 3.4 Failure handling

This matches `local.py`'s split. Failures of *model output* cost their chunk (ADR-023: raise
`ValueError`, and `rebuild.py:334` continues). Failures of *transport* end the run once retries
are exhausted (`local.py:94-96`). Ending the run is the safer failure for transport: a rebuild
that finished with throttled chunks silently missing would commit an incomplete edition in place
of the previous derived layer (ADR-039). It would also be misclassified by
`tests/canary/replay.py:156-160`, which records `ValueError` as a model rejection and
`httpx.HTTPError` as `TRANSPORT_ERROR`.

**Transport (retried, then ends the run):**

- Retries cover `{429, 500, 502, 503, 504}` and `httpx.TransportError`, with three attempts,
  structured as `local.py:97-141`.
- A 429 waits `retry-after-ms / 1000` if that header is present and parseable, else
  `Retry-After` seconds, else `backoff_seconds`. The wait is **capped at 60 seconds**, so one
  header cannot sleep through the job timeout.
- On the last attempt the response is returned, and the adapter raises
  `httpx.HTTPStatusError`. It is not a `ValueError`, so it ends the run, as an exhausted 5xx does
  in `local.py`.
- Any other non-2xx (400, 401, 404, …) raises the same way and ends the run: a wrong key,
  deployment or api-version fails on the first chunk, not after 204 of them. The one exception is
  the content-filter 400 below.
- The exception's message is `Azure OpenAI {status} {error.code}: {error.message}`, the message
  cut to 300 characters, read from the body's `error` object. httpx's own text names only the
  status and URL, which cannot tell an effort/model mismatch, a refused schema keyword and a
  missing deployment apart. A body with no `error` object falls back to httpx's text. It stays an
  `HTTPStatusError` because `rebuild.py` and the canary replay classify on that type.

**Configuration (ends the run):**

- A `model` mismatch (§3.3) raises `ServedModelMismatch`, before anything is cached.

**Model output (costs the chunk, raises `ValueError` naming the cause):**

- A content-filter refusal. This is either a `400` whose `error.code` is `content_filter`
  (checked before `raise_for_status`) or `choices[0].finish_reason == "content_filter"`.
- A refusal: `choices[0].message.refusal` is non-null, or `message.content` is null. Strict
  `json_schema` can return a refusal with `content: null`, and `json.loads(None)` would raise a
  `TypeError` that `rebuild.py:334` does not catch.
- Truncation (`finish_reason == "length"`) raises a message in the same form as `local.py`'s for
  `done_reason == "length"`, naming `AZURE_OPENAI_MAX_OUTPUT_TOKENS` as the cap. When the response
  carries `usage.completion_tokens_details.reasoning_tokens`, the message says how many of the
  capped tokens went to reasoning. For a reasoning model the usual truncation is reasoning
  consuming the budget before any answer is written, and "the answer was cut off" would send a
  reader to the wrong fix.
- Content that is not JSON raises `ValueError("model output was not JSON: ...")`, truncated to
  200 characters, as `local.py` does.
- Any other malformed shape raises `ValueError` naming it, never the `AttributeError` or
  `TypeError` that `rebuild.py:334` would let end the run: a body, choice or message that is not
  an object, content that is not a string, content that parses to something other than an
  object, or an `obligations` that is not a list (a missing one is read as none). The content
  checks live in `schema.payload_items`, shared with `local.py`.

### 3.5 Kept guards (cheap, not accreditation)

At construction, each of these raises a `ValueError` naming the problem:

- The endpoint scheme must be `https`.
- The endpoint host must be `azure.us` or end in `.azure.us`. The check compares whole DNS labels
  of the parsed hostname, so `notazure.us` and `azure.us.example.com` are refused. The project
  owner directed this so that a mistyped or commercial (`*.azure.com`) endpoint fails at startup.
- The endpoint is the base URL alone: a path other than `/`, a query, a fragment or userinfo is
  refused, naming what to remove (a path would double the `/openai/` route the adapter adds). A
  port is allowed. The message does not echo the endpoint, since userinfo can hold a password.
- The key, deployment, api-version and model must each be non-empty.

And throughout:

- The key is a `pydantic.SecretStr` in Settings, held privately by the adapter. It never appears
  in a log line, an exception message, or `repr(adapter)`. `SecretStr` is safe here because
  nothing iterates or dumps `Settings`.
- Exception messages carry no chunk text. The only excerpt is the one `local.py` already
  includes: 200 characters of *model output* on a parse failure.

### 3.6 Settings, wiring, compose

`backend/src/policy_grapher/config.py`:

- The `extractor_adapter` comment becomes `"null" | "local" | "azure"`. The default stays
  `"null"`.
- New fields, defaulting empty so nothing is read unless `azure` is configured:
  `azure_openai_endpoint: str = ""`, `azure_openai_api_key: SecretStr = SecretStr("")`,
  `azure_openai_deployment: str = ""`, `azure_openai_api_version: str = ""` and
  `azure_openai_model: str = ""`.
- `azure_openai_reasoning_effort: str = ""`: empty for gpt-4o, set for reasoning models (§3.1).
- `azure_openai_max_output_tokens: int = 16384`. This is the adapter's own cap, not
  `extractor_max_output_tokens`. That 2048 was measured for llama3.1:8b as about four times the
  largest real answer (554 tokens, `config.py:69-80`). A reasoning model's reasoning tokens count
  against the same cap, so 2048 could be spent before the answer starts. 16384 is gpt-4o's maximum
  output and leaves room for reasoning at `low` and `medium`. It is a ceiling, not a measurement:
  what reasoning actually costs per chunk is found in the live check (§7) and the default revised
  from that, as `extractor_max_output_tokens` was.

`backend/src/policy_grapher/extraction/__init__.py`: `build_extractor` gains an `"azure"` branch
before the `raise ValueError` at line 72.

`docker-compose.yml`:

- The `backend` (around `:61-101`) and `worker` (around `:175-210`) services list their
  environment explicitly, and the container has no `.env` (`config.py:6-9`). Without changes,
  `EXTRACTOR_ADAPTER=azure` crashes the backend at boot (`main.py:118`) on an empty endpoint.
- Both services gain the seven `AZURE_OPENAI_*` variables of this section, as `${VAR:-}`, empty by
  default, except `AZURE_OPENAI_MAX_OUTPUT_TOKENS`, which defaults to `16384`.
- `test_config_composition.py` is extended so that both services pass all seven through.

`.env.example`:

- A commented-out Azure block after the extractor settings (around line 41), with the key as an
  **empty value**. It is not an `init-env.sh` placeholder: that script would copy one verbatim
  and send it as a credential.
- A note beside it covering three things:
  - one worked example per available deployment: gpt-4o with the effort empty, and gpt-5.1 and
    gpt-5.6-luna with `AZURE_OPENAI_REASONING_EFFORT=low`;
  - that `AZURE_OPENAI_MODEL` must be the dated version Azure returns;
  - that a 204-chunk edition is 204 metered calls, while the floors tests skip for an unmeasured
    adapter, so `uv run pytest` does not spend **as long as the Azure settings are in `.env`**.
    Tests that build `Settings(_env_file=None)` still read the process environment, so
    `EXTRACTOR_ADAPTER=azure` exported in the shell reaches the integration rebuild tests and they
    bill. The settings go in `.env` for both host-run and compose, which reads `.env` for its
    `${VAR}` interpolation.

## 4. Tests

The new tests go in `backend/tests/test_extraction_adapters.py`, all against a stub
`httpx.MockTransport`, all offline. Each is written first and seen to fail.

1. `build_extractor` returns `AzureOpenAIExtractor` for `"azure"`, and still raises on an unknown
   name. With the default `null`, no Azure setting is read.
2. Construction refuses each of the following, with a message naming what is wrong:
   - `http://`;
   - a host outside `*.azure.us`: `notazure.us`, `azure.us.example.com`, `x.openai.azure.com`;
   - an empty key;
   - an empty deployment, api-version or model.
3. The request has:
   - the documented URL;
   - the `api-key` header;
   - the `api-version` query;
   - the right `response_format` for each decoding mode.
3a. With the effort empty, the body has `temperature: 0` and `max_tokens`, and no
    `reasoning_effort` or `max_completion_tokens`. With the effort set, it has
    `max_completion_tokens` and `reasoning_effort` equal to the setting, and no `temperature` or
    `max_tokens`. Both caps equal `azure_openai_max_output_tokens`.
4. `STRICT_SCHEMA` has `additionalProperties: false` and a full `required` list on every object,
   and **none of the §3.2 stripped keywords anywhere**.
5. `cache_variant` changes when `STRICT_SCHEMA` changes (tested by patching the digest input),
   when the api-version changes, when the decoding mode changes, and when the reasoning effort
   changes.
6. Valid items come back as `ExtractedObligation`. An invalid item is dropped, and `on_drop` is
   called once with its reason while its valid siblings survive.
7. Each of these raises `ValueError` naming the cause:
   - `finish_reason: "length"`, with the message naming the reasoning-token count when `usage`
     carries one;
   - a content-filter 400;
   - `finish_reason: "content_filter"`;
   - a non-null `refusal`;
   - `content: null`;
   - each malformed shape of §3.4: a body, choice or message that is not an object, content that
     is not a string, a payload that is not an object, and `obligations: null`.
7a. A `model` mismatch raises `ServedModelMismatch`, which is not a `ValueError`, so a rebuild
    ends on the first chunk.
8. For a 429 with `retry-after-ms` and then success, the sleep honours the header. `Retry-After`
   alone is honoured too, and a 3600-second header is capped at 60.
9. Three 429s raise `httpx.HTTPStatusError`, not `ValueError`, so a rebuild ends. A 401 raises
   on the first attempt with no retry.
10. The key appears in no exception message and not in `repr(adapter)`.
11. `adapter_id` changes when `azure_openai_model` changes.

Also:

12. `test_responsibilities_coverage.py`: with a stub adapter whose `adapter_id` has no `FLOORS`
    entry, the coverage test skips without calling `extract`.
13. `test_config_composition.py`: backend and worker both pass the seven `AZURE_OPENAI_*`
    variables.

Per standing practice, a new test that passes on its first run is checked by mutating the exact
property it guards and seeing it fail. For example: remove the label-boundary check for test 2,
drop the `retry-after-ms` read for test 8, or make the 429 path raise `ValueError` for test 9.

Verification on this machine:

- `cd backend && uv run pytest` is green.
- A fresh clone with no `.env` still starts and passes.
- `docker compose config` shows the seven variables on both services.

## 5. What is not built

- No `openai` SDK, and no Entra ID or managed-identity auth: key only.
- No Responses API and no v1 route (§3.1); Chat Completions on the deployment path only.
- No validation of the effort value against the model (§3.1); Azure is the authority.
- No embedding adapter on Azure. ADR-016's port is untouched, and `embedder_adapter` stays
  `null | local`.
- No `/ask` or other generation path. Extraction only.
- No floors, no accreditation constant, and no `US_ORIGIN_MODELS` change (§2).

## 6. The record: ADR-043, and the docs it touches

### ADR-043

The file is
`docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md`, on the current
template.

- **Header.** "Amends [ADR-041](…) and [ADR-020](…)", in the same form ADR-041 uses for "Amends
  ADR-016".
- **Context.**
  - The project is in closed development and testing.
  - ADR-041 and ADR-020 require an accreditation record and a US-origin set entry, and the
  two-adapter plan adds measured floors, before a managed adapter is used.
  - None of those can be honestly produced yet, and the project owner wants a working adapter
  now.
- **Decision.** While the corpus is in closed development and holds no real CUI, the Azure
  OpenAI adapter:
  - may send corpus text to an `https://*.azure.us` endpoint without an ADR-041 accreditation
    record;
  - may serve a model that is not in ADR-020's set;
  - runs without recorded floors. The floors tests skip for it loudly, as they do for any
    unmeasured adapter.

  The `null` default stands.
- **What ends it.** Either of two triggers, whichever comes first: the first real CUI entering
  the corpus, or any use beyond closed development and testing. At that point ADR-043 is
  superseded and the gates return:
  - ADR-041's accreditation record;
  - an ADR-020 set entry by its own recorded decision;
  - the two-adapter plan's U3–U6.
- **Consequences.** A working managed extractor now, and an explicit, dated debt with a named
  trigger.

### Status lines

These follow the existing linked form, e.g. ADR-013's "Accepted, amended by
[ADR-034](ADR-034-a-statement-is-a-quotation.md)". The bodies of the ADRs are untouched.

- **ADR-020:** "Accepted, amended by [ADR-043](…)". ADR-020 is on the older template, whose header
  permits marking.
- **ADR-013:** gains ", [ADR-041](…)". This is the cross-reference the two-adapter plan's U5
  already owed. ADR-041 itself never claims to amend ADR-013, so this records the plan's debt,
  not a new amendment.
- **ADR-041 is not edited.** Its header reads "Dated record — written once, not edited
  afterward", so the amendment is recorded only in ADR-043's own header, the way ADR-041 records
  its amendment of ADR-016.

### Other documents touched

AGENTS.md:116 and CONVENTIONS require that a change to behaviour updates the relevant spec.

- **`docs/specs/architecture.md`:** the adapter lists (around :476 and :570) gain `azure`,
  citing ADR-043.
- **`README.md`:** the adapter list gains `azure` and its variables.
- **The two-adapter plan:** a note under its Readiness block that U3–U6 are suspended while
  ADR-043 is in force, pointing here.

## 7. Live verification is manual, on a secure machine

The live API key cannot be used on this development machine. The work is complete here when the
§4 suite is green offline. The claim that it works against Azure is verified by the project owner
on a secure machine, using these steps, which go in the PR description:

1. Set these in `.env`, for both host-run and compose (compose reads `.env` to interpolate
   `${VAR}`), not in the shell, where they would also reach the test suite's `Settings(_env_file=None)`
   and make the integration rebuild tests bill: `EXTRACTOR_ADAPTER=azure`,
   `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`,
   `AZURE_OPENAI_API_VERSION` and `AZURE_OPENAI_MODEL`, plus `AZURE_OPENAI_REASONING_EFFORT` for
   gpt-5.1 and gpt-5.6-luna.
2. Run a one-chunk smoke test: a `uv run python -c` that builds the extractor via
   `build_extractor(Settings())` and extracts one gold fixture. This confirms:
   - auth and the URL shape;
   - that strict-schema acceptance works with the stripped keywords;
   - that the returned `model` matches `AZURE_OPENAI_MODEL`, and records each deployment's exact
     dated string;
   - that each of gpt-4o, gpt-5.1 and gpt-5.6-luna is reachable on the deployment path with its
     request shape (§3.1);
   - `usage.completion_tokens_details.reasoning_tokens` per chunk at the chosen effort, which is
     the measurement that revises the 16384 default (§3.6).
3. Rebuild one small edition through the UI or API, and confirm obligations appear on its
   document page.

A scores-only run of the gold set is **not** provided. The floors tests skip for an unmeasured
adapter (§2), and recording a placeholder floor to make them run is exactly what
`test_no_recorded_floor_is_unfailable` refuses. Measuring the model is the returning U6's job.

Anything that fails there is reported as a bug against this adapter, not treated as a floor or
accreditation question: a keyword Azure refuses, a `model` string in a different form, a
parameter a deployment rejects.
