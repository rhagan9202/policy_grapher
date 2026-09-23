# Azure OpenAI Extraction Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `EXTRACTOR_ADAPTER=azure` extracts obligations through an Azure Government OpenAI deployment
(gpt-4o, gpt-5.1 or gpt-5.6-luna) using an API key, host-run and under compose, with the `null`
default and a key-free CI untouched.

**Architecture:** A new adapter module, `extraction/azure_openai.py`, is a peer of `local.py` behind
the existing `ObligationExtractor` port. It uses plain `httpx` against the Chat Completions
deployment route. The per-item validation loop that `local.py` owns moves into `schema.py`, so both
adapters drop items identically (ADR-030). ADR-043 records that closed development relaxes ADR-041's
accreditation record, ADR-020's model set and the floors gate for this adapter. The floors tests
already skip for an unmeasured adapter; the responsibilities-coverage test is brought into line so
`pytest` never spends Azure calls.

**Tech Stack:** Python 3, FastAPI app settings via pydantic-settings, `httpx` (with
`httpx.MockTransport` in tests), pytest, docker compose.

**Spec:** `docs/superpowers/specs/2026-09-23-azure-openai-extraction-adapter-design.md` (rev. 3,
approved 2026-09-23). Read it before starting. Every design decision below argues from it.

## Global Constraints

- The live Azure key **cannot be used on this machine**. Every test runs offline against
  `httpx.MockTransport`. Do not attempt a live call. Live verification is the project owner's, on a
  secure machine (Task 7 writes the steps).
- `extractor_adapter` default stays `"null"`. Nothing reads an Azure setting unless
  `extractor_adapter == "azure"`.
- Endpoint must be `https` and its host `azure.us` or end in `.azure.us`, matched on whole labels.
- Two request shapes, chosen by `azure_openai_reasoning_effort` and never by model name:
  - empty → `temperature: 0`, `max_tokens`;
  - set → `max_completion_tokens`, `reasoning_effort`, and no `temperature`.
- `azure_openai_max_output_tokens` default is `16384`. It is the adapter's own cap, not
  `extractor_max_output_tokens`.
- `adapter_id = "azure:" + azure_openai_model`.
- `cache_variant = f"{decoding}@{api_version}#{schema_digest}~{effort or '-'}"`. The digest is
  `"-"` in `json` mode.
- Model-output failures raise `ValueError`, which costs the chunk. Transport failures, including
  exhausted 429s, raise `httpx` errors, which end the run.
- Retry waits are capped at 60 seconds.
- The key never appears in a log line, an exception message or `repr(adapter)`.
- No `openai` SDK, no Responses API, no v1 route, no Entra ID, no embedding adapter, no floors, no
  accreditation constant, and no `US_ORIGIN_MODELS` change.
- Commit messages follow the repo's style: `type: a sentence saying what is now true`, lower case,
  a prose body, ending with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Every test that passes on its first run is checked by mutating the exact property it guards
  (standing practice). Each task names the mutation.
- Run tests from `backend/`: `cd backend && uv run pytest …`.

---

## File map

| File | Change | Responsibility |
| --- | --- | --- |
| `backend/tests/test_responsibilities_coverage.py` | modify | skip for unmeasured adapters (Task 1) |
| `backend/src/policy_grapher/extraction/schema.py` | modify | gains `validate_items`, the shared ADR-030 loop (Task 2) |
| `backend/src/policy_grapher/extraction/local.py` | modify | uses `validate_items` (Task 2) |
| `backend/src/policy_grapher/config.py` | modify | seven `azure_openai_*` fields (Task 3) |
| `backend/src/policy_grapher/extraction/azure_openai.py` | create | the adapter (Tasks 3–5) |
| `backend/tests/test_azure_openai_adapter.py` | create | the adapter's tests (Tasks 3–6) |
| `backend/src/policy_grapher/extraction/__init__.py` | modify | `"azure"` branch in `build_extractor` (Task 6) |
| `docker-compose.yml` | modify | seven variables on backend and worker (Task 6) |
| `backend/tests/test_config_composition.py` | modify | guard that both services pass them (Task 6) |
| `.env.example` | modify | commented Azure block (Task 6) |
| `docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md` | create | the record (Task 7) |
| `docs/specs/adr/ADR-020-…`, `ADR-013-…` | modify | status lines only (Task 7) |
| `docs/specs/architecture.md`, `README.md`, the two-adapter plan | modify | docs (Task 7) |

The spec places the adapter tests in `test_extraction_adapters.py`. This plan gives them their own
file instead: that file is already 600+ lines about `local`, and the Azure tests share fixtures
nothing else uses.

---

### Task 1: The coverage test skips for an unmeasured adapter

This comes first because without it, any `.env` naming `azure` makes the rest of this work spend
money on every test run (spec §2).

**Files:**
- Modify: `backend/tests/test_responsibilities_coverage.py:112-126` (`test_enough_of_the_responsibilities_section_is_read`)

**Interfaces:**
- Consumes: `FLOORS` from `backend/tests/test_obligation_ratchet.py:200`. It is a dict keyed by
  `adapter_id`, and `null` is never a key (`test_no_recorded_floor_is_unfailable`).
- Produces: nothing new. Later tasks rely on this test skipping for `azure:*`.

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_responsibilities_coverage.py`:

```python
def test_an_unmeasured_adapter_is_neither_gated_nor_spent_on(monkeypatch):
    """Spec §2. The coverage floor used to skip only for `null`, so a `.env` naming
    any other adapter sent every responsibilities chunk to it on every run, and
    held a model nobody had measured to the 0.80 floor. It now follows the
    ratchet's rule: no recorded floors, no gate and no calls."""

    class Unmeasured:
        adapter_id = "unmeasured:test"
        cache_variant = ""

        def extract(self, *args, **kwargs):
            raise AssertionError("an unmeasured adapter was called")

    monkeypatch.setattr(
        sys.modules[__name__], "build_extractor", lambda settings: Unmeasured()
    )
    with pytest.raises(pytest.skip.Exception, match="has no recorded floors"):
        test_enough_of_the_responsibilities_section_is_read(sorted(EXPECTED_ROLE_ITEMS)[0])
```

Add `import sys` to the file's imports.

- [ ] **Step 2: Run it to verify it fails.**

Run: `cd backend && uv run pytest tests/test_responsibilities_coverage.py::test_an_unmeasured_adapter_is_neither_gated_nor_spent_on -v`
Expected: FAIL with `AssertionError: an unmeasured adapter was called`, because the current guard
checks only `settings.extractor_adapter == "null"`. If `Settings()` picks up a real `.env` naming
`null`, the failure may instead be `Failed: DID NOT RAISE` on the skip. Either failure is the
right one.

- [ ] **Step 3: Implement.** In `test_responsibilities_coverage.py`:
  - Add `from test_obligation_ratchet import FLOORS` beside the other imports. Tests import sibling
    modules this way already, e.g. `from support import STAMP` in `test_export.py:12`.
  - Replace the `null` guard in `test_enough_of_the_responsibilities_section_is_read` with:

```python
    settings = Settings()
    extractor = build_extractor(settings)
    # The ratchet's rule (test_obligation_ratchet.py:321-330), for the same reason:
    # an adapter nobody has measured is not held to a floor, and is not called.
    # `null` is never in FLOORS, so this still covers it — and it covers a managed
    # adapter (ADR-043) that would otherwise be billed for every chunk on every run.
    if extractor.adapter_id not in FLOORS:
        pytest.skip(
            f"THE COVERAGE FLOOR DID NOT RUN: {extractor.adapter_id!r} has no recorded "
            f"floors. A green suite does not mean coverage held — it means nothing "
            f"checked."
        )
```

- [ ] **Step 4: Run it to verify it passes, and the file still collects.**

Run: `cd backend && uv run pytest tests/test_responsibilities_coverage.py -v -rs`
Expected: the new test PASSES. The integration tests skip with "has no recorded floors" when `.env`
names `null`, or run as before when it names `local`.

- [ ] **Step 5: Mutation check.** Temporarily change the guard back to `if settings.extractor_adapter == "null":`, confirm the new test FAILS, then restore it.

- [ ] **Step 6: Commit.**

```bash
git add backend/tests/test_responsibilities_coverage.py
git commit -m "test: the coverage floor neither gates nor calls an adapter nobody measured

It skipped only for null, so a .env naming any other adapter sent a whole
responsibilities section to it on every run and held an unmeasured model to
the 0.80 floor. It now follows the ratchet's rule: no recorded floors, no
gate and no calls. Needed before the Azure adapter, which is metered.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The per-item validation loop becomes shared

`local.py:176-210` owns the ADR-030 loop: validate each item, drop failures through `on_drop`, and
reject the chunk when nothing validated but something failed. The Azure adapter needs exactly this
loop. Copying it would put ADR-030 in two places, so it moves, unchanged in behaviour.

**Files:**
- Modify: `backend/src/policy_grapher/extraction/schema.py` (append after `validate_extracted`, line ~231)
- Modify: `backend/src/policy_grapher/extraction/local.py:174-210`
- Test: `backend/tests/test_extraction_schema.py`

**Interfaces:**
- Produces: `validate_items(items: list, *, section_title: str | None, chunk_text: str, on_drop: Callable[[str], None] | None) -> list[ExtractedObligation]`, in `policy_grapher.extraction.schema`. It raises `ValueError(first_reason)` when `items` had failures and nothing validated.

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_extraction_schema.py`:

```python
from policy_grapher.extraction.schema import validate_items

_GOOD = {
    "statement": "The Director shall notify the Comptroller.",
    "modality": "SHALL",
    "actor": "The Director",
    "deadline": None,
    "conditions": None,
    "confidence": 0.9,
}
_BAD = {**_GOOD, "modality": None}
_CHUNK = "The Director shall notify the Comptroller.\n"


def test_validate_items_drops_the_bad_item_and_keeps_its_sibling():
    dropped: list[str] = []
    found = validate_items(
        [_GOOD, _BAD], section_title=None, chunk_text=_CHUNK, on_drop=dropped.append
    )
    assert [o.statement for o in found] == [_GOOD["statement"]]
    assert len(dropped) == 1
    assert dropped[0].startswith("model output did not match the obligation schema")


def test_validate_items_rejects_a_chunk_where_nothing_validated():
    with pytest.raises(ValueError, match="did not match the obligation schema"):
        validate_items([_BAD], section_title=None, chunk_text=_CHUNK, on_drop=None)


def test_validate_items_treats_an_empty_list_as_an_answer():
    assert validate_items([], section_title=None, chunk_text=_CHUNK, on_drop=None) == []
```

Add `import pytest` at the top if the file doesn't already import it.

- [ ] **Step 2: Run to verify it fails.**

Run: `cd backend && uv run pytest tests/test_extraction_schema.py -k validate_items -v`
Expected: FAIL with `ImportError: cannot import name 'validate_items'`.

- [ ] **Step 3: Implement.** Append to `schema.py`, and add `from collections.abc import Callable` to its imports if absent:

```python
def validate_items(
    items: list,
    *,
    section_title: str | None,
    chunk_text: str,
    on_drop: Callable[[str], None] | None,
) -> list[ExtractedObligation]:
    """ADR-030's loop, shared by every adapter that parses a model's answer.

    Each item is validated on its own, and one that fails costs itself rather
    than everything that shared its chunk. Measured 2026-08-26: eight chunks in
    thirty-seven were lost whole, every one of them to a single `modality: null`
    on a sentence stating scope and naming no duty. The strictness is unchanged —
    `Modality` is still closed and an invalid item is still not written. What
    changed is the blast radius.

    Here rather than in one adapter because two adapters parse answers, and a
    rule living in only one of them is a rule the other silently lacks.
    """
    found: list[ExtractedObligation] = []
    reasons: list[str] = []
    for item in items:
        try:
            found.append(
                validate_extracted(item, section_title=section_title, chunk_text=chunk_text)
            )
        # `ValueError`, not `ValidationError`: ADR-033's section guard is not a
        # field rule and raises plainly, and `ValidationError` subclasses
        # `ValueError`, so this catches both without knowing which rule refused.
        except ValueError as exc:
            reason = f"model output did not match the obligation schema: {exc}"
            reasons.append(reason)
            if on_drop is not None:
                on_drop(reason)

    # Nothing validated out of something the model did return: that is a wholly
    # broken answer, not a passage without duties, and ADR-030 keeps it a
    # rejected chunk. An empty list is the ordinary case and stays an answer.
    if reasons and not found:
        raise ValueError(reasons[0])
    return found
```

Then, in `local.py`, replace everything from the `# ADR-030. Each item is validated…` comment
through `return found` at the end of `extract` with:

```python
        return validate_items(
            payload.get("obligations", []),
            section_title=section_title,
            chunk_text=chunk_text,
            on_drop=on_drop,
        )
```

Change `local.py`'s schema import to bring in `validate_items` instead of `validate_extracted`, and
drop `ExtractedObligation` only if nothing else in `local.py` uses it. It is still in `extract`'s
return annotation, so keep it.

- [ ] **Step 4: Run the new tests and every existing local-adapter test.**

Run: `cd backend && uv run pytest tests/test_extraction_schema.py tests/test_extraction_adapters.py -v`
Expected: all PASS. The local tests at `test_extraction_adapters.py:350-480` (drops, rejections,
the ASSIGNED section guard) are the behaviour guard for the move.

- [ ] **Step 5: Mutation check.** In `validate_items`, delete the `if reasons and not found: raise` block. Confirm `test_validate_items_rejects_a_chunk_where_nothing_validated` **and** `test_a_chunk_where_nothing_validates_is_still_rejected` both FAIL. Restore it.

- [ ] **Step 6: Commit.**

```bash
git add backend/src/policy_grapher/extraction/schema.py backend/src/policy_grapher/extraction/local.py backend/tests/test_extraction_schema.py
git commit -m "refactor: the per-item validation loop lives beside the schema it applies

ADR-030's loop was local.py's alone. The Azure adapter parses answers too,
and a copy would be a second place for the rule to drift. Behaviour is
unchanged; the local adapter's drop and rejection tests are the guard.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Settings, the strict schema, and construction

**Files:**
- Modify: `backend/src/policy_grapher/config.py` (after `extractor_max_output_tokens`, line 80)
- Create: `backend/src/policy_grapher/extraction/azure_openai.py`
- Create: `backend/tests/test_azure_openai_adapter.py`

**Interfaces:**
- Produces, in `policy_grapher.extraction.azure_openai`:
  - `STRICT_SCHEMA: dict`
  - `UNSUPPORTED_KEYWORDS: frozenset[str]`
  - `schema_digest(schema: dict) -> str`, which returns 12 hex characters
  - `MAX_RETRY_WAIT_SECONDS = 60.0`
  - `class AzureOpenAIExtractor`, with a keyword-only constructor:
    `endpoint: str`, `api_key: SecretStr | str`, `deployment: str`, `api_version: str`,
    `model: str`, `reasoning_effort: str = ""`, `max_output_tokens: int = 16384`,
    `decoding: str = "schema"`, `timeout_seconds: float = 600.0`,
    `transport: httpx.BaseTransport | None = None`, `backoff_seconds: float = 2.0`,
    `sleep: Callable[[float], None] = time.sleep`
  - Properties `adapter_id: str` and `cache_variant: str`, and `__repr__`.
- Produces, on `Settings`: `azure_openai_endpoint: str`, `azure_openai_api_key: SecretStr`,
  `azure_openai_deployment: str`, `azure_openai_api_version: str`, `azure_openai_model: str`,
  `azure_openai_reasoning_effort: str`, `azure_openai_max_output_tokens: int`.

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/test_azure_openai_adapter.py`:

```python
"""The Azure OpenAI extraction adapter (spec: docs/superpowers/specs/
2026-09-23-azure-openai-extraction-adapter-design.md). Every test is offline:
the live key cannot be used on this machine, and a test that needed it would
have strayed into the manual check the spec's §7 describes."""

import json

import httpx
import pytest
from pydantic import SecretStr

from policy_grapher.extraction import azure_openai
from policy_grapher.extraction.azure_openai import (
    STRICT_SCHEMA,
    UNSUPPORTED_KEYWORDS,
    AzureOpenAIExtractor,
)

KEY = "k-3f9a-not-a-real-key"
MODEL = "gpt-4o-2024-11-20"
ENDPOINT = "https://policy-grapher.openai.azure.us"


def _adapter(handler=None, **overrides) -> AzureOpenAIExtractor:
    kwargs = dict(
        endpoint=ENDPOINT,
        api_key=SecretStr(KEY),
        deployment="extract",
        api_version="2025-04-01-preview",
        model=MODEL,
        backoff_seconds=0,
        sleep=lambda seconds: None,
    )
    kwargs.update(overrides)
    if handler is not None:
        kwargs["transport"] = httpx.MockTransport(handler)
    return AzureOpenAIExtractor(**kwargs)


# --- construction ------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint,named",
    [
        ("http://policy-grapher.openai.azure.us", "https"),
        ("https://notazure.us", "azure.us"),
        ("https://azure.us.example.com", "azure.us"),
        ("https://x.openai.azure.com", "azure.us"),
    ],
)
def test_an_endpoint_outside_azure_government_over_https_is_refused(endpoint, named):
    with pytest.raises(ValueError, match=named):
        _adapter(endpoint=endpoint)


def test_an_azure_government_host_is_accepted():
    _adapter(endpoint="https://policy-grapher.openai.azure.us/")


@pytest.mark.parametrize(
    "field,setting",
    [
        ("api_key", "AZURE_OPENAI_API_KEY"),
        ("deployment", "AZURE_OPENAI_DEPLOYMENT"),
        ("api_version", "AZURE_OPENAI_API_VERSION"),
        ("model", "AZURE_OPENAI_MODEL"),
    ],
)
def test_an_empty_required_setting_is_refused_by_name(field, setting):
    with pytest.raises(ValueError, match=setting):
        _adapter(**{field: SecretStr("") if field == "api_key" else ""})


def test_an_unknown_decoding_mode_is_refused():
    with pytest.raises(ValueError, match="decoding"):
        _adapter(decoding="grammar")


def test_the_key_is_not_in_the_repr():
    assert KEY not in repr(_adapter())


def test_a_refused_construction_does_not_echo_the_key():
    with pytest.raises(ValueError) as caught:
        _adapter(api_key=SecretStr(KEY), endpoint="http://x.azure.us")
    assert KEY not in str(caught.value)


# --- identity ------------------------------------------------------------------


def test_the_adapter_id_names_the_model_version():
    assert _adapter().adapter_id == f"azure:{MODEL}"
    assert _adapter(model="gpt-5.1-2025-11-13").adapter_id == "azure:gpt-5.1-2025-11-13"


def test_the_cache_variant_moves_with_everything_that_changes_an_answer(monkeypatch):
    base = _adapter().cache_variant
    assert _adapter(api_version="2024-10-21").cache_variant != base
    assert _adapter(decoding="json").cache_variant != base
    assert _adapter(reasoning_effort="low").cache_variant != base
    assert _adapter(reasoning_effort="low").cache_variant != _adapter(
        reasoning_effort="high"
    ).cache_variant
    monkeypatch.setattr(azure_openai, "STRICT_SCHEMA", {**STRICT_SCHEMA, "title": "moved"})
    assert _adapter().cache_variant != base


def test_the_cache_variant_ignores_the_output_cap():
    """A cap changes whether an answer completes, not what a completed one says,
    and a truncated answer is never cached (spec §3.3)."""
    assert _adapter(max_output_tokens=4096).cache_variant == _adapter().cache_variant


# --- the strict schema --------------------------------------------------------


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for key, value in node.items():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def _keywords(node, *, is_map=False):
    """Every schema keyword in use, skipping the names inside `properties`/`$defs`."""
    if isinstance(node, list):
        for value in node:
            yield from _keywords(value)
    elif isinstance(node, dict):
        for key, value in node.items():
            if not is_map:
                yield key
            yield from _keywords(value, is_map=not is_map and key in ("properties", "$defs"))


def test_every_object_in_the_strict_schema_is_closed_and_fully_required():
    objects = list(_objects(STRICT_SCHEMA))
    assert objects, "the walk found no objects; the test is looking at the wrong thing"
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])


def test_the_strict_schema_carries_no_keyword_azure_refuses():
    assert set(_keywords(STRICT_SCHEMA)).isdisjoint(UNSUPPORTED_KEYWORDS)


def test_stripping_keywords_leaves_a_property_that_shares_a_keyword_name():
    schema = azure_openai._strict(
        {"type": "object", "properties": {"format": {"type": "string", "format": "date"}}}
    )
    assert schema["properties"] == {"format": {"type": "string"}}
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'policy_grapher.extraction.azure_openai'`.

- [ ] **Step 3: Add the settings.** In `config.py`:
  - add `from pydantic import SecretStr` to the imports;
  - change the `extractor_adapter` comment to `# "null" | "local" | "azure"`;
  - insert after `extractor_max_output_tokens: int = 2048`:

```python

    # Azure OpenAI on Azure Government (ADR-043, closed development only). Read only
    # when extractor_adapter is "azure"; every default is empty so nothing else
    # notices them. The endpoint must be https on *.azure.us, checked at startup.
    azure_openai_endpoint: str = ""
    azure_openai_api_key: SecretStr = SecretStr("")
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = ""
    # The dated version the deployment returns in `model` (e.g. gpt-4o-2024-11-20),
    # not the deployment name. It is the adapter id and so the cache key, and every
    # response is checked against it: an alias retargeted behind a stable name would
    # otherwise have its answers cached under the old model.
    azure_openai_model: str = ""
    # Empty for gpt-4o (temperature 0, max_tokens). Set — none/low/medium/high —
    # for a reasoning model such as gpt-5.1 or gpt-5.6-luna, which rejects both of
    # those and takes max_completion_tokens and reasoning_effort instead. Passed
    # through unvalidated: Azure is the authority on what each model accepts.
    azure_openai_reasoning_effort: str = ""
    # Not extractor_max_output_tokens: that 2048 was measured for llama3.1:8b, and
    # a reasoning model's hidden reasoning spends the same budget before the answer
    # starts. 16384 is a ceiling, not a measurement — revise it from the reasoning
    # tokens the live check records (spec §7).
    azure_openai_max_output_tokens: int = 16384
```

- [ ] **Step 4: Create the module.** Write `backend/src/policy_grapher/extraction/azure_openai.py`:

```python
"""An Azure OpenAI deployment on Azure Government, reached with an API key.

A peer of `local.py`, not a parameterisation of it: `adapter_id` keys the cache
and the floors table, and one id over two providers makes both meaningless.
ADR-043 records why this adapter runs, during closed development, without the
accreditation record ADR-041 asks for, outside ADR-020's model set, and without
floors.

**Metered.** Every chunk is one billed call, and a 204-chunk edition is 204
calls. The floors tests skip for an adapter with no recorded floors, so
`uv run pytest` on a machine whose `.env` names this adapter spends nothing; a
rebuild does. There is no spend cap here on purpose: a limit inside the
extractor would stop an edition halfway, which is worse than a bill. The
account's own budget controls are the place for one.

Every response is still validated against our own schema, as in `local.py`,
because that is what keeps behaviour identical across adapters.
"""

import hashlib
import json
import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from policy_grapher.extraction.prompt import EXTRACTION_PROMPT
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    ExtractionPayload,
    validate_items,
)

DEFAULT_TIMEOUT_SECONDS = 600.0
DEFAULT_BACKOFF_SECONDS = 2.0
DEFAULT_MAX_OUTPUT_TOKENS = 16384
# A Retry-After header is Azure's to set, and one large value would otherwise
# sleep a rebuild through its whole job timeout.
MAX_RETRY_WAIT_SECONDS = 60.0

# Azure structured outputs' documented unsupported type-specific keywords.
# ExtractedObligation carries the first four. Dropping them loses nothing:
# `validate_items` enforces the full model on every item regardless.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "format",
    }
)


def _strict(node, *, is_map: bool = False):
    """A copy of a JSON Schema that strict `json_schema` mode accepts.

    Every object is closed and lists every property as required, which strict
    mode demands; unsupported keywords are dropped. `is_map` marks a dict whose
    keys are names (`properties`, `$defs`), not keywords, so a property that
    happens to be called `format` survives.
    """
    if isinstance(node, list):
        return [_strict(value) for value in node]
    if not isinstance(node, dict):
        return node
    if is_map:
        return {name: _strict(value) for name, value in node.items()}
    out = {
        key: _strict(value, is_map=key in ("properties", "$defs"))
        for key, value in node.items()
        if key not in UNSUPPORTED_KEYWORDS
    }
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


# Once at import, as local.py does with its schema: a pure function of the models.
STRICT_SCHEMA = _strict(ExtractionPayload.model_json_schema())


def schema_digest(schema: dict) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:12]


def _check_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    if parts.scheme != "https":
        raise ValueError(
            f"AZURE_OPENAI_ENDPOINT must use https, not {parts.scheme or 'no scheme'!r}: "
            f"this adapter sends policy text with a key attached."
        )
    host = (parts.hostname or "").lower()
    # Whole labels: `notazure.us` and `azure.us.example.com` are not Azure
    # Government, and a bare suffix test would let both through.
    if host != "azure.us" and not host.endswith(".azure.us"):
        raise ValueError(
            f"AZURE_OPENAI_ENDPOINT host {host!r} is not on azure.us. This adapter "
            f"targets Azure Government only (ADR-043); a commercial *.azure.com "
            f"endpoint is refused rather than silently used."
        )
    return endpoint.rstrip("/")


class AzureOpenAIExtractor:
    def __init__(
        self,
        *,
        endpoint: str,
        api_key: SecretStr | str,
        deployment: str,
        api_version: str,
        model: str,
        reasoning_effort: str = "",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        decoding: str = "schema",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        for value, setting in (
            (key.get_secret_value(), "AZURE_OPENAI_API_KEY"),
            (deployment, "AZURE_OPENAI_DEPLOYMENT"),
            (api_version, "AZURE_OPENAI_API_VERSION"),
            (model, "AZURE_OPENAI_MODEL"),
        ):
            if not value:
                raise ValueError(f"{setting} is empty; the azure adapter cannot run without it")
        if decoding not in ("schema", "json"):
            raise ValueError(f"unknown decoding mode: {decoding!r}")

        self._endpoint = _check_endpoint(endpoint)
        self._deployment = deployment
        self._api_version = api_version
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._decoding = decoding
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        # Read at construction, not import, so the digest is of the schema this
        # instance actually sends.
        self._schema = STRICT_SCHEMA
        self._schema_digest = schema_digest(self._schema) if decoding == "schema" else "-"
        # The key lives only in the client's headers. httpx's errors name the URL
        # and status, never the request headers.
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout_seconds,
            headers={"api-key": key.get_secret_value()},
        )
        self._url = f"{self._endpoint}/openai/deployments/{deployment}/chat/completions"

    def __repr__(self) -> str:
        return (
            f"AzureOpenAIExtractor(adapter_id={self.adapter_id!r}, "
            f"endpoint={self._endpoint!r}, deployment={self._deployment!r})"
        )

    @property
    def adapter_id(self) -> str:
        return f"azure:{self._model}"

    @property
    def cache_variant(self) -> str:
        effort = self._reasoning_effort or "-"
        return f"{self._decoding}@{self._api_version}#{self._schema_digest}~{effort}"
```

- [ ] **Step 5: Run the tests.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -v`
Expected: all PASS.

- [ ] **Step 6: Mutation checks.** Apply each mutation, confirm the named test FAILS, then restore:
  - `host.endswith(".azure.us")` → `host.endswith("azure.us")`: the `https://notazure.us` case of `test_an_endpoint_outside_azure_government_over_https_is_refused` fails.
  - Delete the `if is_map:` branch in `_strict`: `test_stripping_keywords_leaves_a_property_that_shares_a_keyword_name` fails.
  - Delete `out["additionalProperties"] = False`: `test_every_object_in_the_strict_schema_is_closed_and_fully_required` fails.
  - Drop `~{effort}` from `cache_variant`: `test_the_cache_variant_moves_with_everything_that_changes_an_answer` fails.
  - Change `self._schema = STRICT_SCHEMA` to use a digest computed at import: the `monkeypatch` line of the same test fails.
  - Add `api_key={key.get_secret_value()!r}` to `__repr__`: `test_the_key_is_not_in_the_repr` fails.

- [ ] **Step 7: Commit.**

```bash
git add backend/src/policy_grapher/config.py backend/src/policy_grapher/extraction/azure_openai.py backend/tests/test_azure_openai_adapter.py
git commit -m "feat: an Azure Government extraction adapter can be constructed and named

Settings for the endpoint, key, deployment, api-version, model version,
reasoning effort and output cap; construction refuses anything but https on
azure.us, and any empty setting by name. The adapter id is the model version
Azure returns, and the cache variant carries every other thing that changes
an answer, including the strict schema strict mode is sent.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The request, and reading the answer

**Files:**
- Modify: `backend/src/policy_grapher/extraction/azure_openai.py` (add methods to `AzureOpenAIExtractor`)
- Test: `backend/tests/test_azure_openai_adapter.py`

**Interfaces:**
- Consumes: Task 3's class and `validate_items` from Task 2.
- Produces: `AzureOpenAIExtractor.extract(chunk_text: str, *, section_path: list[str], section_title: str | None = None, on_drop: Callable[[str], None] | None = None) -> list[ExtractedObligation]`, the port signature (`extraction/__init__.py:29-36`). Also `_body(chunk_text, section_path) -> dict` and `_post(body) -> httpx.Response`. Task 5 replaces `_post` with a retrying version under the same name.

- [ ] **Step 1: Write the failing tests.** Append to `test_azure_openai_adapter.py`:

```python
from policy_grapher.extraction.prompt import EXTRACTION_PROMPT

PASSAGE = "1.1.  SCOPE.\nThis issuance applies to the OSD.\nThe Director shall notify the Comptroller.\n"
GOOD = {
    "statement": "The Director shall notify the Comptroller.",
    "modality": "SHALL",
    "actor": "The Director",
    "deadline": None,
    "conditions": None,
    "confidence": 0.88,
}


def _completion(content, *, model=MODEL, finish="stop", refusal=None, usage=None):
    body = {
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _answering(payload, **kwargs):
    content = payload if isinstance(payload, str) or payload is None else json.dumps(payload)
    return lambda request: httpx.Response(200, json=_completion(content, **kwargs))


def _captured(**overrides):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_completion(json.dumps({"obligations": []})))

    return _adapter(handler, **overrides), seen


# --- the request ---------------------------------------------------------------


def test_the_request_goes_to_the_deployment_route_with_the_key():
    adapter, seen = _captured()
    adapter.extract(PASSAGE, section_path=["1", "1.1"])
    (request,) = seen
    assert request.method == "POST"
    assert request.url.path == "/openai/deployments/extract/chat/completions"
    assert request.url.params["api-version"] == "2025-04-01-preview"
    assert request.headers["api-key"] == KEY
    body = json.loads(request.content)
    assert body["messages"] == [
        {
            "role": "user",
            "content": EXTRACTION_PROMPT.format(section_path="1/1.1", chunk_text=PASSAGE),
        }
    ]


def test_schema_decoding_sends_the_strict_schema():
    adapter, seen = _captured(decoding="schema")
    adapter.extract(PASSAGE, section_path=["1"])
    fmt = json.loads(seen[0].content)["response_format"]
    assert fmt == {
        "type": "json_schema",
        "json_schema": {"name": "obligations", "strict": True, "schema": STRICT_SCHEMA},
    }


def test_json_decoding_sends_json_object():
    adapter, seen = _captured(decoding="json")
    adapter.extract(PASSAGE, section_path=["1"])
    assert json.loads(seen[0].content)["response_format"] == {"type": "json_object"}


def test_without_a_reasoning_effort_the_request_is_the_gpt_4o_shape():
    adapter, seen = _captured(max_output_tokens=4096)
    adapter.extract(PASSAGE, section_path=["1"])
    body = json.loads(seen[0].content)
    assert body["temperature"] == 0
    assert body["max_tokens"] == 4096
    assert "reasoning_effort" not in body
    assert "max_completion_tokens" not in body


def test_with_a_reasoning_effort_the_request_is_the_reasoning_shape():
    """gpt-5.1 and gpt-5.6-luna reject temperature and max_tokens (spec §3.1)."""
    adapter, seen = _captured(reasoning_effort="low", max_output_tokens=4096)
    adapter.extract(PASSAGE, section_path=["1"])
    body = json.loads(seen[0].content)
    assert body["reasoning_effort"] == "low"
    assert body["max_completion_tokens"] == 4096
    assert "temperature" not in body
    assert "max_tokens" not in body


# --- the answer ----------------------------------------------------------------


def test_a_well_formed_answer_becomes_obligations():
    result = _adapter(_answering({"obligations": [GOOD]})).extract(PASSAGE, section_path=["1"])
    assert [o.modality for o in result] == ["SHALL"]


def test_an_invalid_item_is_dropped_and_reported_while_its_sibling_survives():
    dropped: list[str] = []
    bad = {**GOOD, "modality": None}
    result = _adapter(_answering({"obligations": [GOOD, bad]})).extract(
        PASSAGE, section_path=["1"], on_drop=dropped.append
    )
    assert len(result) == 1
    assert len(dropped) == 1


@pytest.mark.parametrize(
    "handler,cause",
    [
        (_answering("{}", finish="length"), "AZURE_OPENAI_MAX_OUTPUT_TOKENS"),
        (_answering(None, finish="content_filter"), "content filter"),
        (_answering(None, refusal="I can't help with that."), "refused"),
        (_answering(None), "no content"),
        (_answering("not json"), "not JSON"),
        (_answering({"obligations": []}, model="gpt-4o-2024-08-06"), "gpt-4o-2024-08-06"),
        (
            lambda request: httpx.Response(
                400,
                json={"error": {"code": "content_filter", "message": "filtered"}},
            ),
            "content filter",
        ),
    ],
    ids=["length", "filter-finish", "refusal", "null-content", "not-json", "model-drift", "filter-400"],
)
def test_a_failed_answer_costs_its_chunk_and_names_why(handler, cause):
    """ValueError is what rebuild.py:334 catches: the chunk is rejected, the run goes on."""
    with pytest.raises(ValueError, match=cause):
        _adapter(handler).extract(PASSAGE, section_path=["1"])


def test_a_truncation_says_how_much_went_to_reasoning():
    usage = {"completion_tokens": 16384, "completion_tokens_details": {"reasoning_tokens": 16100}}
    handler = _answering("", finish="length", usage=usage)
    with pytest.raises(ValueError, match="16100 of 16384"):
        _adapter(handler, reasoning_effort="high").extract(PASSAGE, section_path=["1"])


def test_a_client_error_other_than_the_filter_ends_the_run():
    """A wrong key or deployment fails on the first chunk, not after all 204."""
    handler = lambda request: httpx.Response(401, json={"error": {"code": "401"}})
    with pytest.raises(httpx.HTTPStatusError):
        _adapter(handler).extract(PASSAGE, section_path=["1"])


def test_no_failure_message_carries_the_key_or_the_passage():
    for handler in (
        _answering(None, refusal="no"),
        _answering({"obligations": []}, model="other"),
        lambda request: httpx.Response(401, json={}),
    ):
        with pytest.raises(Exception) as caught:
            _adapter(handler).extract(PASSAGE, section_path=["1"])
        assert KEY not in str(caught.value)
        assert "shall notify the Comptroller" not in str(caught.value)
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -v`
Expected: the new tests FAIL with `AttributeError: 'AzureOpenAIExtractor' object has no attribute 'extract'`. Task 3's tests still pass.

- [ ] **Step 3: Implement.** Add to `AzureOpenAIExtractor`:

```python
    def _body(self, chunk_text: str, section_path: list[str]) -> dict:
        body: dict = {
            "messages": [
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(
                        section_path="/".join(section_path), chunk_text=chunk_text
                    ),
                }
            ],
            "response_format": (
                {
                    "type": "json_schema",
                    "json_schema": {"name": "obligations", "strict": True, "schema": self._schema},
                }
                if self._decoding == "schema"
                else {"type": "json_object"}
            ),
        }
        # Chosen by the setting, never by the model's name (spec §3.1). Reasoning
        # models reject temperature and max_tokens; gpt-4o predates the other two.
        # A setting that does not match its model is a 400 on the first chunk,
        # which ends the run with Azure's own words.
        if self._reasoning_effort:
            body["max_completion_tokens"] = self._max_output_tokens
            body["reasoning_effort"] = self._reasoning_effort
        else:
            body["temperature"] = 0
            body["max_tokens"] = self._max_output_tokens
        return body

    def _post(self, body: dict) -> httpx.Response:
        return self._client.post(self._url, params={"api-version": self._api_version}, json=body)

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        response = self._post(self._body(chunk_text, section_path))

        # The content filter answers 400, but about this passage rather than about
        # the request: it costs the chunk (ADR-023), where any other 4xx — a wrong
        # key, deployment or parameter — would fail every chunk and ends the run.
        if response.status_code == 400 and _error_code(response) == "content_filter":
            raise ValueError("Azure OpenAI's content filter refused this chunk (400 content_filter)")
        response.raise_for_status()
        answer = response.json()

        served = answer.get("model")
        if served != self._model:
            raise ValueError(
                f"Azure served {served!r}, but AZURE_OPENAI_MODEL is {self._model!r}. The "
                f"deployment now serves a different model than the one this adapter's id — "
                f"and so the extraction cache — names; update AZURE_OPENAI_MODEL."
            )

        choice = answer["choices"][0]
        message = choice.get("message") or {}
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise ValueError("Azure OpenAI's content filter stopped the answer to this chunk")
        if finish == "length":
            raise ValueError(self._truncation_reason(answer))
        if message.get("refusal"):
            raise ValueError(f"the model refused this chunk: {message['refusal'][:200]!r}")
        raw = message.get("content")
        if raw is None:
            raise ValueError("the model returned no content and no refusal for this chunk")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model output was not JSON: {raw[:200]!r}") from exc

        return validate_items(
            payload.get("obligations", []),
            section_title=section_title,
            chunk_text=chunk_text,
            on_drop=on_drop,
        )

    def _truncation_reason(self, answer: dict) -> str:
        reason = (
            f"the model hit its output cap (AZURE_OPENAI_MAX_OUTPUT_TOKENS="
            f"{self._max_output_tokens}) and its answer was truncated. This chunk is "
            f"rejected rather than partly read."
        )
        details = (answer.get("usage") or {}).get("completion_tokens_details") or {}
        reasoning = details.get("reasoning_tokens")
        if reasoning:
            # For a reasoning model the usual truncation is thinking that spent the
            # budget before any answer began; "cut off" would send a reader to the
            # wrong fix.
            reason += (
                f" The model spent {reasoning} of {self._max_output_tokens} tokens "
                f"reasoning; raise the cap or lower AZURE_OPENAI_REASONING_EFFORT."
            )
        return reason
```

And at module level, below `_check_endpoint`:

```python
def _error_code(response: httpx.Response) -> str | None:
    try:
        return (response.json().get("error") or {}).get("code")
    except (ValueError, AttributeError):
        return None
```

- [ ] **Step 4: Run the tests.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -v`
Expected: all PASS.

- [ ] **Step 5: Mutation checks.** Apply each, confirm the failure, restore:
  - Swap the two branches of the `if self._reasoning_effort:` in `_body`: both shape tests fail.
  - Delete the `if message.get("refusal"):` block: the `refusal` case fails. With `content: None` it now raises "no content" instead, so the match on "refused" is what catches it.
  - Delete the `served != self._model` check: `model-drift` fails.
  - Move the content-filter 400 check below `raise_for_status()`: `filter-400` fails, with `HTTPStatusError` in place of `ValueError`.
  - Drop the `if reasoning:` addition: `test_a_truncation_says_how_much_went_to_reasoning` fails.

- [ ] **Step 6: Commit.**

```bash
git add backend/src/policy_grapher/extraction/azure_openai.py backend/tests/test_azure_openai_adapter.py
git commit -m "feat: the Azure adapter extracts, in the shape each deployment accepts

gpt-4o gets temperature 0 and max_tokens; a reasoning model, named by a set
reasoning effort, gets max_completion_tokens and the effort instead. What the
model says is read the way local.py reads it; a filter, a refusal, a
truncation or a drifted model costs its chunk and says why, and any other
client error ends the run on the first chunk.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Throttling and transient failures are retried; exhaustion ends the run

**Files:**
- Modify: `backend/src/policy_grapher/extraction/azure_openai.py` (replace `_post`)
- Test: `backend/tests/test_azure_openai_adapter.py`

**Interfaces:**
- Consumes: Task 4's `extract`, which calls `self._post(body)`.
- Produces: `AzureOpenAIExtractor.RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})`, `ATTEMPTS = 3`, and `_wait_for(response) -> float`.

- [ ] **Step 1: Write the failing tests.** Append:

```python
# --- retries -----------------------------------------------------------------------


def _sequence(*responses):
    queue = list(responses)
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        return queue.pop(0)

    return handler, calls


def _ok():
    return httpx.Response(200, json=_completion(json.dumps({"obligations": [GOOD]})))


@pytest.mark.parametrize(
    "headers,waited",
    [
        ({"retry-after-ms": "1500", "retry-after": "9"}, 1.5),
        ({"retry-after": "7"}, 7.0),
        ({"retry-after": "3600"}, azure_openai.MAX_RETRY_WAIT_SECONDS),
        ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, 0.25),
        ({}, 0.25),
    ],
    ids=["ms-wins", "seconds", "capped", "http-date-falls-back", "no-header"],
)
def test_a_throttled_call_waits_as_told_and_then_succeeds(headers, waited):
    handler, calls = _sequence(httpx.Response(429, headers=headers), _ok())
    slept: list[float] = []
    adapter = _adapter(handler, backoff_seconds=0.25, sleep=slept.append)
    assert len(adapter.extract(PASSAGE, section_path=["1"])) == 1
    assert slept == [waited]
    assert len(calls) == 2


def test_a_transient_server_error_is_retried():
    handler, calls = _sequence(httpx.Response(503), _ok())
    assert len(_adapter(handler).extract(PASSAGE, section_path=["1"])) == 1
    assert len(calls) == 2


def test_exhausted_throttling_ends_the_run_rather_than_costing_the_chunk():
    """Spec §3.4: a ValueError here would let rebuild.py:334 carry on, and a
    partly throttled rebuild would commit an edition with chunks silently missing."""
    handler, calls = _sequence(*[httpx.Response(429) for _ in range(3)])
    with pytest.raises(httpx.HTTPStatusError, match="429"):
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    assert len(calls) == 3


def test_an_authentication_failure_is_not_retried():
    handler, calls = _sequence(httpx.Response(401), _ok())
    with pytest.raises(httpx.HTTPStatusError):
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    assert len(calls) == 1


def test_a_dropped_connection_is_retried_and_then_ends_the_run():
    calls: list[int] = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("reset", request=request)

    with pytest.raises(httpx.TransportError):
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    assert len(calls) == 3
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -k "throttl or transient or authentication or dropped" -v`
Expected: the throttle and transient tests FAIL. There's no retry yet, so a 429 or 503 goes straight to `raise_for_status`, and `slept` stays empty. `test_an_authentication_failure_is_not_retried` may already pass; that's fine, because it guards against over-retrying, which Step 5 mutates.

- [ ] **Step 3: Implement.** Replace `_post` with:

```python
    # As in local.py: only transport-level failures are retried, and a schema
    # rejection never is. 429 joins the 5xx set here because a managed endpoint
    # throttles as a matter of course, and rebuild.py:334 catches only ValueError,
    # so an unretried 429 would end a whole rebuild on the first busy second.
    RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    ATTEMPTS = 3

    def _post(self, body: dict) -> httpx.Response:
        for attempt in range(1, self.ATTEMPTS + 1):
            last = attempt == self.ATTEMPTS
            try:
                response = self._client.post(
                    self._url, params={"api-version": self._api_version}, json=body
                )
            except httpx.TransportError:
                if last:
                    raise
                self._sleep(self._backoff_seconds)
                continue
            # On the last attempt the response is returned as-is, and extract's
            # raise_for_status ends the run with it — an HTTPStatusError, not a
            # ValueError, so a rebuild stops rather than committing an edition
            # with throttled chunks silently missing (ADR-039).
            if response.status_code not in self.RETRYABLE_STATUS or last:
                return response
            self._sleep(self._wait_for(response))
        raise AssertionError("unreachable: the loop returns or raises on its last pass")

    def _wait_for(self, response: httpx.Response) -> float:
        """Azure's own hint, in milliseconds if given, else seconds, capped."""
        for header, per_second in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
            raw = response.headers.get(header)
            if raw is None:
                continue
            try:
                seconds = float(raw) / per_second
            except ValueError:
                # Retry-After may be an HTTP date; not worth parsing for a wait
                # this adapter caps at a minute anyway.
                continue
            if seconds >= 0:
                return min(seconds, MAX_RETRY_WAIT_SECONDS)
        return self._backoff_seconds
```

- [ ] **Step 4: Run the whole adapter file.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -v`
Expected: all PASS.

- [ ] **Step 5: Mutation checks.** Apply each, confirm the failure, restore:
  - Remove `429` from `RETRYABLE_STATUS`: the throttle tests fail.
  - Swap the tuple order in `_wait_for`, so seconds are read first: `ms-wins` fails.
  - Drop the `min(…, MAX_RETRY_WAIT_SECONDS)`: `capped` fails.
  - Add `401` to `RETRYABLE_STATUS`: `test_an_authentication_failure_is_not_retried` fails.
  - In `extract`, wrap `raise_for_status()` to re-raise as `ValueError`: `test_exhausted_throttling_ends_the_run_rather_than_costing_the_chunk` fails.

- [ ] **Step 6: Commit.**

```bash
git add backend/src/policy_grapher/extraction/azure_openai.py backend/tests/test_azure_openai_adapter.py
git commit -m "feat: the Azure adapter waits out throttling and stops when it cannot

A 429 is retried after retry-after-ms, else Retry-After, capped at a minute;
5xx and dropped connections are retried as in local.py. When every attempt
fails the run ends with the HTTP error rather than a ValueError, so a rebuild
cannot finish with throttled chunks silently missing.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wiring — `build_extractor`, compose, `.env.example`

**Files:**
- Modify: `backend/src/policy_grapher/extraction/__init__.py:57-72`
- Modify: `docker-compose.yml`: `backend` environment after `EXTRACTOR_TIMEOUT_SECONDS` (around line 97), and `worker` environment after its `EXTRACTOR_TIMEOUT_SECONDS` (around line 202)
- Modify: `backend/tests/test_config_composition.py` (append)
- Modify: `.env.example` (after `REBUILD_JOB_TIMEOUT_SECONDS=28800`, around line 45)
- Test: `backend/tests/test_azure_openai_adapter.py`

**Interfaces:**
- Consumes: Task 3's `Settings` fields and the `AzureOpenAIExtractor` constructor.
- Produces: `build_extractor(settings)` returns `AzureOpenAIExtractor` when `settings.extractor_adapter == "azure"`.

- [ ] **Step 1: Write the failing tests.** Append to `test_azure_openai_adapter.py`:

```python
# --- wiring --------------------------------------------------------------------------

from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor


def _settings(**overrides) -> Settings:
    values = dict(
        _env_file=None,
        extractor_adapter="azure",
        azure_openai_endpoint=ENDPOINT,
        azure_openai_api_key=KEY,
        azure_openai_deployment="extract",
        azure_openai_api_version="2025-04-01-preview",
        azure_openai_model=MODEL,
    )
    values.update(overrides)
    return Settings(**values)


def test_build_extractor_returns_the_azure_adapter_when_configured():
    extractor = build_extractor(_settings(azure_openai_reasoning_effort="low"))
    assert isinstance(extractor, AzureOpenAIExtractor)
    assert extractor.adapter_id == f"azure:{MODEL}"
    assert extractor.cache_variant.endswith("~low")


def test_build_extractor_passes_the_azure_output_cap_not_the_local_one():
    seen: list[httpx.Request] = []
    extractor = build_extractor(_settings(azure_openai_max_output_tokens=5000))
    extractor._client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: seen.append(r)
            or httpx.Response(200, json=_completion(json.dumps({"obligations": []})))
        ),
        headers={"api-key": KEY},
    )
    extractor.extract(PASSAGE, section_path=["1"])
    assert json.loads(seen[0].content)["max_tokens"] == 5000


def test_a_misconfigured_azure_adapter_fails_at_startup():
    with pytest.raises(ValueError, match="AZURE_OPENAI_MODEL"):
        build_extractor(_settings(azure_openai_model=""))


def test_the_null_default_reads_no_azure_setting():
    """A broken Azure block in .env must not matter to anyone not using it."""
    settings = _settings(extractor_adapter="null", azure_openai_endpoint="http://nowhere")
    assert build_extractor(settings).adapter_id == "null"
```

And append to `backend/tests/test_config_composition.py`:

```python
AZURE_VARIABLES = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_MODEL",
    "AZURE_OPENAI_REASONING_EFFORT",
    "AZURE_OPENAI_MAX_OUTPUT_TOKENS",
)


@pytest.mark.parametrize("key", AZURE_VARIABLES)
def test_both_extracting_services_can_be_pointed_at_azure(key):
    """The container has no .env (config.py:6-9) and compose lists each variable
    by name, so one missing here never arrives — and EXTRACTOR_ADAPTER=azure then
    fails at boot (main.py:118) on an empty setting. Backend builds the extractor
    at startup; the worker is the one that extracts."""
    compose = COMPOSE.read_text()
    assert compose.count(f"      {key}: ${{{key}:-") == 2, (
        f"{key} must be passed through to both backend and worker in docker-compose.yml"
    )
```

- [ ] **Step 2: Run to verify they fail.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -k "build_extractor or null_default" -v && uv run pytest tests/test_config_composition.py -k azure -v`
Expected: `build_extractor` raises `ValueError: unknown extractor adapter: 'azure'`, and the seven compose tests fail with "must be passed through". `test_the_null_default_reads_no_azure_setting` may already pass; Step 6 mutates it.

- [ ] **Step 3: Implement `build_extractor`.** In `extraction/__init__.py`, insert before the final `raise ValueError(...)`:

```python
    if settings.extractor_adapter == "azure":
        # Imported here, like the others, so a null or local run never loads it.
        from policy_grapher.extraction.azure_openai import AzureOpenAIExtractor

        return AzureOpenAIExtractor(
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            model=settings.azure_openai_model,
            reasoning_effort=settings.azure_openai_reasoning_effort,
            max_output_tokens=settings.azure_openai_max_output_tokens,
            decoding=settings.extractor_decoding,
            timeout_seconds=settings.extractor_timeout_seconds,
        )
```

- [ ] **Step 4: Implement compose.** In `docker-compose.yml`, insert this block into **both** the `backend` and the `worker` `environment:` maps, directly after each one's `EXTRACTOR_TIMEOUT_SECONDS:` line, with the same indentation (six spaces):

```yaml
      # Azure OpenAI on Azure Government (ADR-043). Read only when
      # EXTRACTOR_ADAPTER=azure. Listed one by one because this container has no
      # .env: a variable not named here never arrives.
      AZURE_OPENAI_ENDPOINT: ${AZURE_OPENAI_ENDPOINT:-}
      AZURE_OPENAI_API_KEY: ${AZURE_OPENAI_API_KEY:-}
      AZURE_OPENAI_DEPLOYMENT: ${AZURE_OPENAI_DEPLOYMENT:-}
      AZURE_OPENAI_API_VERSION: ${AZURE_OPENAI_API_VERSION:-}
      AZURE_OPENAI_MODEL: ${AZURE_OPENAI_MODEL:-}
      AZURE_OPENAI_REASONING_EFFORT: ${AZURE_OPENAI_REASONING_EFFORT:-}
      AZURE_OPENAI_MAX_OUTPUT_TOKENS: ${AZURE_OPENAI_MAX_OUTPUT_TOKENS:-16384}
```

The defaults must equal `config.py`'s: empty strings, and `16384`. The existing
`test_a_compose_default_agrees_with_the_application_default` checks each one automatically. The
`SecretStr("")` default compares equal to `SecretStr("")` there.

- [ ] **Step 5: Implement `.env.example`.** Insert after `REBUILD_JOB_TIMEOUT_SECONDS=28800`:

```bash

# Azure OpenAI on Azure Government, instead of the local model (ADR-043: closed
# development only — no accreditation record, no floors). Uncomment one block
# and set EXTRACTOR_ADAPTER=azure above.
#
# METERED: every chunk is one billed call, and a 204-chunk edition is 204 calls.
# `uv run pytest` does not spend: the floors tests skip for an adapter with no
# recorded floors. A rebuild does spend. Cap spend with the Azure account's own
# budget controls; this adapter deliberately has none.
#
# The endpoint must be https on *.azure.us. AZURE_OPENAI_MODEL is the dated
# version the deployment returns in `model`, not the deployment name; a
# response from any other model is rejected. Leave the key empty here and set
# it only in your own .env: init-env.sh does not substitute it.
#
# gpt-4o — no reasoning effort; runs at temperature 0.
# AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.us
# AZURE_OPENAI_API_KEY=
# AZURE_OPENAI_DEPLOYMENT=<your gpt-4o deployment name>
# AZURE_OPENAI_API_VERSION=2025-04-01-preview
# AZURE_OPENAI_MODEL=gpt-4o-2024-11-20
#
# gpt-5.1 or gpt-5.6-luna — reasoning models: they reject temperature, so a
# reasoning effort must be set (none, low, medium or high; not minimal).
# Reasoning tokens count against AZURE_OPENAI_MAX_OUTPUT_TOKENS.
# AZURE_OPENAI_DEPLOYMENT=<your gpt-5.1 or gpt-5.6-luna deployment name>
# AZURE_OPENAI_MODEL=gpt-5.1-2025-11-13
# AZURE_OPENAI_REASONING_EFFORT=low
# AZURE_OPENAI_MAX_OUTPUT_TOKENS=16384
```

The model version strings are examples. The live check (spec §7) records the exact strings each
deployment returns, and this block is corrected from those.

- [ ] **Step 6: Run the tests and a mutation check.**

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py tests/test_config_composition.py tests/test_extraction_adapters.py -v`
Expected: all PASS.

Mutations (apply, confirm the failure, restore):
- Delete the block from the `worker` service only: `test_both_extracting_services_can_be_pointed_at_azure` fails for every key.
- Pass `max_output_tokens=settings.extractor_max_output_tokens` in `build_extractor`: `test_build_extractor_passes_the_azure_output_cap_not_the_local_one` fails.
- Move the `"azure"` branch above the `"null"` branch, constructing Azure unconditionally: `test_the_null_default_reads_no_azure_setting` fails.

- [ ] **Step 7: Commit.**

```bash
git add backend/src/policy_grapher/extraction/__init__.py docker-compose.yml backend/tests/test_config_composition.py .env.example backend/tests/test_azure_openai_adapter.py
git commit -m "feat: EXTRACTOR_ADAPTER=azure reaches the adapter, host-run and in compose

build_extractor learns the third name. Compose lists its environment one
variable at a time and the container has no .env, so all seven Azure
settings are passed to backend and worker, guarded by a test. .env.example
carries a block per available deployment and says what a rebuild costs.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The record — ADR-043, status lines, and the docs that describe adapters

**Files:**
- Create: `docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md`
- Modify: `docs/specs/adr/ADR-020-model-weights-come-from-us-organisations.md:3` (status line only)
- Modify: `docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md:3` (status line only)
- Modify: `docs/specs/architecture.md`: the model-server paragraph (around line 474) and the "Extraction quality is not gated by CI" bullet (around line 569)
- Modify: `README.md`, around lines 119-122, where the adapters are introduced
- Modify: `docs/plans/2026-09-22-1130-feat-two-adapters-ingestion-and-managed-extraction-plan.md`, under its Readiness block (line 15)
- **Do not modify** `ADR-041`. Its header says "written once, not edited afterward", so the amendment lives in ADR-043's header.

- [ ] **Step 1: Write ADR-043.** Use this content, following `TEMPLATE-adr.md` and ADR-041's header form:

```markdown
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
it. The two-adapter plan (docs/plans/2026-09-22-1130-…) adds measured floors, and a gate that fails
rather than skips without them. None of the three can be honestly produced yet: nobody has recorded
an accreditation, no supply-chain decision has added a GPT model, and floors are a measurement of a
model this machine cannot call.

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
```

- [ ] **Step 2: Status lines.** Edit only line 3 of each:
  - ADR-020: `**Status:** Accepted` → `**Status:** Accepted, amended by [ADR-043](ADR-043-closed-development-relaxes-managed-inference-gates.md)`, keeping the rest of the line.
  - ADR-013: `amended by [ADR-034](ADR-034-a-statement-is-a-quotation.md)` → `amended by [ADR-034](ADR-034-a-statement-is-a-quotation.md), [ADR-041](ADR-041-accredited-managed-inference-is-permitted.md)`. This is the cross-reference the two-adapter plan's U5 already owed. ADR-041 itself never claims to amend ADR-013.

- [ ] **Step 3: architecture.md.**
  - After the sentence ending "…enforced by a test rather than a comment." in the model-server paragraph (around line 481), add: `A third extractor, `azure`, sends chunks to an Azure Government OpenAI deployment (gpt-4o, gpt-5.1 or gpt-5.6-luna) with an API key; during closed development it runs without an accreditation record, outside the US-origin set and without floors ([ADR-043](adr/ADR-043-closed-development-relaxes-managed-inference-gates.md)), and every one of its settings is passed to backend and worker because the container has no `.env`.`
  - In the "Extraction quality is not gated by CI" bullet (around line 569), after its first sentence add: `The same skip applies to `azure` (ADR-043), and to `test_enough_of_the_responsibilities_section_is_read`, so a machine configured for a metered adapter spends nothing on a test run.`

- [ ] **Step 4: README.md.** After the paragraph ending "…without any further setup." (around line 122), add:

```markdown
To extract through an Azure Government OpenAI deployment instead of the local model, set
`EXTRACTOR_ADAPTER=azure` and the `AZURE_OPENAI_*` block in `.env.example` (endpoint, key,
deployment, api-version, model version, and a reasoning effort for gpt-5.1 or gpt-5.6-luna).
Every chunk is a billed call. This is permitted during closed development only
([ADR-043](docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md)).
```

- [ ] **Step 5: The two-adapter plan.** Insert after its Readiness blockquote (line 15):

```markdown
> **Superseded in part, 2026-09-23.** While
> [ADR-043](../specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md) is in force,
> U5 and U6 are replaced by `docs/superpowers/specs/2026-09-23-azure-openai-extraction-adapter-design.md`
> (the provider is Azure Government OpenAI), and U3 and U4 are suspended, since either one as written
> fails the suite for that adapter. All four return as written when ADR-043 ends. U1, U2, U7 and U8
> are unaffected.
```

- [ ] **Step 6: Check links resolve.**

Run: `cd /home/rhagan/policy_grapher && for f in docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md docs/specs/adr/ADR-041-accredited-managed-inference-is-permitted.md docs/specs/adr/ADR-020-model-weights-come-from-us-organisations.md; do test -f "$f" && echo ok "$f"; done; grep -rn "ADR-043" docs README.md | wc -l`
Expected: three `ok` lines and a non-zero count. The repo has no automated docs-link test, so this check is the whole of it.

- [ ] **Step 7: Commit.**

```bash
git add docs/specs/adr/ADR-043-closed-development-relaxes-managed-inference-gates.md docs/specs/adr/ADR-020-model-weights-come-from-us-organisations.md docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md docs/specs/architecture.md README.md docs/plans/2026-09-22-1130-feat-two-adapters-ingestion-and-managed-extraction-plan.md
git commit -m "docs: closed development relaxes the managed-inference gates, in writing

ADR-043 lets the Azure adapter run without ADR-041's accreditation record,
outside ADR-020's set and without floors, until real CUI enters the corpus
or use goes beyond closed development. ADR-041 is not edited, as its header
asks; ADR-043 carries the amendment. The two-adapter plan marks U3-U6
suspended, and the architecture and README name the third adapter.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Verification, and the manual check handed to the owner

**Files:** none changed, unless a step finds a bug. If one does, fix it in its own commit before
continuing (standing rule: fix every bug found).

- [ ] **Step 1: The full suite.**

Run: `cd backend && uv run pytest -rs > /tmp/azure-suite.txt 2>&1; echo "exit=$?"; tail -30 /tmp/azure-suite.txt`
Expected: exit 0. The verdict is the exit code, not the count. Skips should include "has no recorded floors" for the coverage test when `.env` names `null` or `azure`.

- [ ] **Step 2: A fresh clone with no `.env` (spec AE6).**

Run:
```bash
FRESH=$(mktemp -d) && git clone -q /home/rhagan/policy_grapher "$FRESH/repo" && cd "$FRESH/repo/backend" && test ! -e ../.env && uv run pytest -q -m "not integration" > "$FRESH/out.txt" 2>&1; echo "exit=$?"; tail -5 "$FRESH/out.txt"
```
Expected: exit 0, with no `.env` present.

- [ ] **Step 3: Compose resolves the variables on both services.**

Run: `cd /home/rhagan/policy_grapher && EXTRACTOR_ADAPTER=azure AZURE_OPENAI_MODEL=probe docker compose config 2>&1 | grep -c "AZURE_OPENAI_MODEL: probe"`
Expected: `2`. If `docker` is unreachable from this sandbox, record that in the PR and rely on `test_both_extracting_services_can_be_pointed_at_azure` instead. The environment may be a Flatpak sandbox, so check `/.flatpak-info` before concluding docker is absent.

- [ ] **Step 4: Offline proof.** Confirm the adapter tests need no network:

Run: `cd backend && uv run pytest tests/test_azure_openai_adapter.py -q -p no:cacheprovider 2>&1 | tail -3`
Expected: all pass. They use `MockTransport` throughout, so no socket is opened.

- [ ] **Step 5: Write the manual check into the PR description.** The owner runs it on a secure machine. Copy verbatim:

```markdown
## Live check (manual, on a secure machine — the key cannot be used on the dev machine)

1. In `.env` (host-run) or the shell (compose): `EXTRACTOR_ADAPTER=azure`, `AZURE_OPENAI_ENDPOINT`,
   `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`,
   `AZURE_OPENAI_MODEL`, plus `AZURE_OPENAI_REASONING_EFFORT=low` for gpt-5.1 / gpt-5.6-luna.
2. One-chunk smoke, per deployment (gpt-4o, gpt-5.1, gpt-5.6-luna):
   `cd backend && uv run python -c "from policy_grapher.config import Settings; from policy_grapher.extraction import build_extractor; e = build_extractor(Settings()); print(e.adapter_id, e.extract('The Director shall notify the Comptroller within 30 days.', section_path=['1']))"`
   - A `ValueError` naming a different served model: set `AZURE_OPENAI_MODEL` to the string it
     names, and report that string so `.env.example` can be corrected.
   - A 400 naming `temperature`/`max_tokens`/`reasoning_effort`: the effort setting doesn't match
     the model (empty for gpt-4o, set for gpt-5.x).
   - A 400 about `response_format` or a schema keyword: report it as a bug against the adapter.
   - A 404: the deployment path isn't served for this model on Azure Government; report it (the
     v1 route is the fallback, spec §3.1).
3. Record `usage.completion_tokens_details.reasoning_tokens` for a few chunks at the chosen effort
   (for example via a debug print of `response.json()["usage"]`). It revises the 16384 default.
4. Rebuild one small edition through the UI or API, and confirm obligations appear on its document
   page.
```

- [ ] **Step 6: Report.** Say plainly which of Steps 1–4 passed, and paste any failure output. State that the live check is outstanding and belongs to the owner. Then use superpowers:finishing-a-development-branch.
