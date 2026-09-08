# Constrained Decoding and Blast Radius — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a change to the extractor bounded, reproducible, and visible — by pinning the runtime every measurement rests on, constraining the model to the schema rather than asking it for JSON, running the quality gate on every push, and recording what a prompt change moves.

**Architecture:** Four layers, in dependency order. The model runtime is pinned so measurements mean something. The cache key is widened to cover what actually varies the answer, so a decoding change cannot be served stale results. The adapter then passes a JSON Schema to Ollama's `format` field instead of the string `"json"`, which makes enum and type violations unemittable rather than caught after the fact. Finally the gate runs per-push against a smaller model, and a canary set records what moves when the prompt changes.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2, pytest, Ollama (llama3.1:8b and llama3.2:3b), Neo4j, Docker Compose, GitHub Actions.

**Spec:** [`docs/artifacts/research/2026-08-31-architecture-and-workflow-research.md`](../../artifacts/research/2026-08-31-architecture-and-workflow-research.md)

## Global Constraints

- **Sprint 12 is open and this work folds into it.** Per [CONVENTIONS](../../CONVENTIONS.md), `sprint-12/plan.md` is a frozen dated record — **do not edit it**. The added scope is recorded in `sprint-12/review.md` at close.
- **Never close an unfinished sprint**, and **never leave a known bug unfixed** — the two standing rules in [`AGENTS.md`](../../../AGENTS.md), set by the project owner. A defect found while doing this work is fixed in code before the work is reported finished.
- **Floors ratchet up, never down.** A red floor is fixed in the extractor, not in the floor. Lowering one needs a reason in the commit message.
- **A floor is truncated below the measurement, never rounded to it.** The comparison is `measured < floor`, so a rounded-up floor sits above the number it came from.
- **Set a floor from the lowest observation across processes**, not the tidiest one inside a single run.
- **Change one thing when a number is going to be read from it.** Sprint 10 lost an hour to changing the prompt and the guard together.
- **One model-bound job at a time.** Ollama serialises; a second concurrent job makes both slower and corrupts any timing measurement.
- **Model provenance is a procurement constraint**, not a preference: extraction models must be published by a US organisation (ADR-020). `llama3.2:3b` is Meta and already in `US_ORIGIN_MODELS`.
- **Anything that changes what the model produces for the same chunk must change the cache key.** This is the invariant [`cache.py`](../../../backend/src/policy_grapher/extraction/cache.py) already states in its docstring.
- Commits use Conventional Commit prefixes (`feat:`, `fix:`, `test:`, `docs:`), imperative and specific.
- Backend tests: `cd backend && uv run pytest`. Skip container-backed tests with `-m "not integration"`.

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `docker-compose.yml` | Pins `ollama/ollama` to an exact version in both services | 1 |
| `backend/tests/test_compose_stack.py` | Asserts no model service floats on `:latest` | 1 |
| `backend/src/policy_grapher/extraction/__init__.py` | `ObligationExtractor` gains `cache_variant` | 2 |
| `backend/src/policy_grapher/extraction/cache.py` | `cache_key` covers the variant | 2 |
| `backend/src/policy_grapher/extraction/null.py` | Null adapter's empty variant | 2 |
| `backend/src/policy_grapher/extraction/local.py` | Runtime version, decoding mode, schema in `format` | 2, 3 |
| `backend/src/policy_grapher/extraction/schema.py` | `ExtractionPayload` envelope, for schema generation only | 3 |
| `backend/src/policy_grapher/config.py` | `extractor_decoding` setting | 3 |
| `backend/tests/test_obligation_ratchet.py` | Floors for a second adapter | 4, 5 |
| `.github/workflows/ci.yml` | Per-push extraction gate against llama3.2:3b | 5 |
| `backend/tests/canary/` + `backend/tests/fixtures/canary/` | Blast-radius baseline and diff | 6 |
| `docs/sprints/standing-actions.md` | Living home for standing actions | 7 |

---

### Task 1: Pin the model runtime

Finding 1b. This must land first: every measurement in Tasks 4–6 is taken against this runtime, and pinning afterwards pins an unknown.

**Files:**
- Modify: `docker-compose.yml:254` and `docker-compose.yml:274`
- Test: `backend/tests/test_compose_stack.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a pinned runtime version string, used verbatim in `.github/workflows/ci.yml` in Task 5.

- [ ] **Step 1: Find the version actually in use**

Do not invent a version. Read it from the running server, so the pin records what the floors were measured against rather than whatever is newest today.

```bash
docker compose up -d ollama
until curl -sf http://localhost:11434/api/version; do sleep 2; done
curl -s http://localhost:11434/api/version
```

Expected: JSON like `{"version":"0.6.2"}`. Use that exact value below wherever this plan writes `<PINNED>`.

- [ ] **Step 2: Write the failing test**

Add to `backend/tests/test_compose_stack.py`. `COMPOSE` and `MODEL_SERVICES` already exist at the top of that file.

```python
def test_the_model_services_pin_their_image():
    """`latest` makes the model runtime depend on when it was last pulled.

    STORY-018 pinned neo4j for this reason and architecture.md records it. The
    reasoning is stronger here: the runtime's version determines sampling and
    decoding — the machinery that produces every number in FLOORS — so an
    unpinned runtime means extraction behaviour can change with no commit, no
    PROMPT_VERSION bump, and nothing to review.
    """
    for name in MODEL_SERVICES:
        image = COMPOSE["services"][name]["image"]
        assert not image.endswith(":latest"), (
            f"{name} runs {image!r}; pin it to a version. An unpinned model "
            "runtime silently invalidates every floor in test_obligation_ratchet.py"
        )
        assert ":" in image, f"{name} runs {image!r} with no tag at all, which is :latest"
```

- [ ] **Step 3: Run it to make sure it fails**

```bash
cd backend && uv run pytest tests/test_compose_stack.py::test_the_model_services_pin_their_image -v
```

Expected: FAIL — `ollama runs 'ollama/ollama:latest'; pin it to a version.`

- [ ] **Step 4: Pin both services**

In `docker-compose.yml`, change both occurrences (the `ollama` service at line 254 and `ollama-pull` at line 274):

```yaml
    image: ollama/ollama:<PINNED>
```

Add this comment above the `ollama` service's `image:` line:

```yaml
    # Pinned for the same reason neo4j is (STORY-018), and with more force: this
    # runtime's version determines sampling and decoding, which is what produces
    # the numbers in tests/test_obligation_ratchet.py. On `latest` those floors
    # would be measured against whatever was pulled that morning. Upgrading is a
    # deliberate commit that re-measures the floors, not a side effect of time.
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd backend && uv run pytest tests/test_compose_stack.py -v
```

Expected: PASS, and every other test in the file still passes.

- [ ] **Step 6: Mutate the guard before believing it**

The standing action from sprint 9: a new test that passes first time is suspect. Keep a copy, do not revert.

```bash
cp docker-compose.yml /tmp/compose-backup.yml
sed -i 's|ollama/ollama:<PINNED>|ollama/ollama:latest|' docker-compose.yml
cd backend && uv run pytest tests/test_compose_stack.py::test_the_model_services_pin_their_image -v
cp /tmp/compose-backup.yml ../docker-compose.yml
```

Expected: FAIL while mutated, PASS after restoring. If it passes while mutated, the test is vacuous — fix it before continuing.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml backend/tests/test_compose_stack.py
git commit -m "fix: the model runtime is pinned, so a floor measures something repeatable"
```

---

### Task 2: The cache key covers everything that varies the answer

Finding 1b, second half. Task 3 changes what the model produces for an unchanged chunk. The cache key currently holds `adapter_id` and `prompt_version` and nothing else, so without this task Task 3 would be served stale results and measure nothing.

**Files:**
- Modify: `backend/src/policy_grapher/extraction/__init__.py`
- Modify: `backend/src/policy_grapher/extraction/cache.py`
- Modify: `backend/src/policy_grapher/extraction/null.py`
- Modify: `backend/src/policy_grapher/extraction/local.py`
- Test: `backend/tests/test_extraction_cache.py` (create if absent; otherwise add to it)

**Interfaces:**
- Consumes: Task 1's pinned runtime.
- Produces:
  - `ObligationExtractor.cache_variant: str` — every adapter has one; `""` means "nothing beyond the adapter id varies my answer".
  - `cache_key(chunk_text, *, section_path, adapter_id, prompt_version, variant="") -> str`
  - `LocalExtractor.runtime_version: str` — lazily fetched once from `GET /api/version`, `"unknown"` if the server will not say.

- [ ] **Step 1: Write the failing tests**

Create or add to `backend/tests/test_extraction_cache.py`:

```python
from policy_grapher.extraction.cache import cache_key


def test_the_variant_changes_the_key():
    """Two runs that differ only in how the model was constrained are different
    questions and must not share an answer."""
    common = dict(section_path=["1"], adapter_id="local:llama3.1:8b", prompt_version=4)
    assert cache_key("text", **common, variant="json@0.6.2") != cache_key(
        "text", **common, variant="schema@0.6.2"
    )


def test_the_runtime_version_changes_the_key():
    """An upgraded runtime is a different asker even when nothing else moved."""
    common = dict(section_path=["1"], adapter_id="local:llama3.1:8b", prompt_version=4)
    assert cache_key("text", **common, variant="schema@0.6.2") != cache_key(
        "text", **common, variant="schema@0.7.0"
    )


def test_an_absent_variant_keeps_the_old_key():
    """Adapters with nothing extra to say must not invalidate their own cache
    merely because the parameter now exists."""
    common = dict(section_path=["1"], adapter_id="null", prompt_version=4)
    assert cache_key("text", **common) == cache_key("text", **common, variant="")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd backend && uv run pytest tests/test_extraction_cache.py -v
```

Expected: FAIL — `cache_key() got an unexpected keyword argument 'variant'`.

- [ ] **Step 3: Widen `cache_key`**

In `backend/src/policy_grapher/extraction/cache.py`, replace the `cache_key` function:

```python
def cache_key(
    chunk_text: str,
    *,
    section_path: list[str],
    adapter_id: str,
    prompt_version: int,
    variant: str = "",
) -> str:
    content = hashlib.sha256(
        f"{'/'.join(section_path)}\n{chunk_text}".encode()
    ).hexdigest()
    # `variant` is empty for an adapter whose answer is fully determined by its
    # id — appending nothing then leaves the key byte-identical to the one this
    # cache was filled under, so widening the key does not throw the cache away.
    return f"{adapter_id}|{prompt_version}|{variant}|{content}" if variant else (
        f"{adapter_id}|{prompt_version}|{content}"
    )
```

Extend the module docstring's list of what the key covers — it currently says "three things":

```
- **the adapter and the prompt version**, because both change the asker.
- **the adapter's variant**, when it has one: the model runtime's version and
  the decoding mode. Both change what the same model returns for the same
  prompt, and neither is visible in the adapter id. This is the same rule as
  the one above, applied to the two things that were silently exempt from it.
```

- [ ] **Step 4: Add `cache_variant` to the port**

In `backend/src/policy_grapher/extraction/__init__.py`, inside the `ObligationExtractor` Protocol, below `adapter_id`:

```python
    adapter_id: str

    cache_variant: str
    """Anything beyond `adapter_id` that varies this adapter's answer.

    Empty when nothing does. Mandatory rather than optional for the same reason
    `on_drop` is: a caller that has to ask which adapter it is holding has lost
    the point of the port.
    """
```

- [ ] **Step 5: Implement it on both adapters**

In `backend/src/policy_grapher/extraction/null.py`, below `adapter_id = "null"`:

```python
    # Nothing varies an answer that is always empty.
    cache_variant = ""
```

In `backend/src/policy_grapher/extraction/local.py`, add to `__init__` and the properties:

```python
        self._runtime_version: str | None = None

    @property
    def runtime_version(self) -> str:
        """The model server's version, asked once and remembered.

        Part of the cache variant because a runtime upgrade changes sampling and
        decoding. `"unknown"` rather than an exception when the server will not
        answer: a cache that degrades to over-keying is safe, and failing
        extraction because a version endpoint is missing is not.
        """
        if self._runtime_version is None:
            try:
                response = self._client.get(f"{self._base_url}/api/version")
                response.raise_for_status()
                self._runtime_version = response.json()["version"]
            except (httpx.HTTPError, KeyError, ValueError):
                self._runtime_version = "unknown"
        return self._runtime_version

    @property
    def cache_variant(self) -> str:
        return f"{self._decoding}@{self.runtime_version}"
```

`self._decoding` is set in Task 3. For this task, add `self._decoding = "json"` in `__init__` so the property resolves; Task 3 makes it configurable.

- [ ] **Step 6: Pass the variant through `CachedExtractor`**

In `cache.py`, inside `CachedExtractor.extract`, change the `cache_key(...)` call:

```python
        key = cache_key(
            chunk_text,
            section_path=section_path,
            adapter_id=self._inner.adapter_id,
            prompt_version=self._prompt_version,
            variant=self._inner.cache_variant,
        )
```

- [ ] **Step 7: Run the tests**

```bash
cd backend && uv run pytest tests/test_extraction_cache.py tests/test_extraction_adapters.py -v
cd backend && uv run pytest -m "not integration"
```

Expected: PASS, all of it. If `test_extraction_adapters.py` has a fake adapter, it now needs a `cache_variant = ""`.

- [ ] **Step 8: Commit**

```bash
git add backend/src/policy_grapher/extraction/ backend/tests/test_extraction_cache.py
git commit -m "feat: the cache key covers the runtime and the decoding mode it was filled under"
```

---

### Task 3: The model is constrained by the schema, not asked for JSON

Finding 1. `"format": "json"` is Ollama's legacy mode and guarantees only that the output parses. Passing the JSON Schema makes field names, types and **enum membership** unemittable.

**Files:**
- Modify: `backend/src/policy_grapher/extraction/schema.py`
- Modify: `backend/src/policy_grapher/extraction/local.py:66-83`
- Modify: `backend/src/policy_grapher/config.py:52-58`
- Modify: `backend/src/policy_grapher/extraction/__init__.py` (`build_extractor`)
- Test: `backend/tests/test_extraction_adapters.py`

**Interfaces:**
- Consumes: `cache_variant` from Task 2.
- Produces:
  - `ExtractionPayload` — a Pydantic model used **only** for `model_json_schema()`, never for parsing.
  - `Settings.extractor_decoding: str` — `"schema"` (default) or `"json"`.
  - `LocalExtractor(..., decoding: str = "schema")`.

- [ ] **Step 1: Add the envelope, for schema generation only**

In `backend/src/policy_grapher/extraction/schema.py`, below `ExtractedObligation`:

```python
class ExtractionPayload(BaseModel):
    """The envelope the model fills — the shape `local.py` already expects.

    **Generated from, never parsed with.** Parsing a whole response through this
    would make one invalid item fail every item that shared its chunk, which is
    exactly the blast radius ADR-030 shrank. Items stay validated one at a time
    by `validate_extracted`. This exists so the server can be handed a schema,
    and so that schema cannot drift from the models it is generated from.
    """

    obligations: list[ExtractedObligation]
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_extraction_adapters.py`:

```python
import json

import httpx

from policy_grapher.extraction.local import LocalExtractor
from policy_grapher.extraction.schema import ExtractionPayload


def test_the_schema_names_every_modality():
    """The enum is what makes `modality: null` unemittable, and null modalities
    cost eight chunks in thirty-seven when measured 2026-08-26."""
    schema = json.dumps(ExtractionPayload.model_json_schema())
    for member in ("SHALL", "MUST", "WILL", "SHOULD", "MAY", "ASSIGNED"):
        assert member in schema, f"{member} is missing from the generated schema"


def test_schema_decoding_sends_the_schema_as_format():
    """`format: "json"` is Ollama's legacy mode: it guarantees the output parses
    and enforces nothing about its shape."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"response": '{"obligations": []}'})

    extractor = LocalExtractor(
        base_url="http://model",
        model="llama3.1:8b",
        transport=httpx.MockTransport(handler),
        decoding="schema",
    )
    extractor.extract("text", section_path=["1"])

    assert isinstance(sent["format"], dict), (
        f"format was {sent['format']!r}; a string is the legacy JSON mode"
    )
    assert sent["format"]["properties"]["obligations"]["type"] == "array"


def test_json_decoding_still_sends_the_legacy_string():
    """Kept switchable so the two can be measured against each other with one
    variable moving, and because a hosted adapter may not constrain at all."""
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"response": '{"obligations": []}'})

    extractor = LocalExtractor(
        base_url="http://model",
        model="llama3.1:8b",
        transport=httpx.MockTransport(handler),
        decoding="json",
    )
    extractor.extract("text", section_path=["1"])

    assert sent["format"] == "json"
```

- [ ] **Step 3: Run them to verify they fail**

```bash
cd backend && uv run pytest tests/test_extraction_adapters.py -k "schema or json_decoding" -v
```

Expected: FAIL — `LocalExtractor.__init__() got an unexpected keyword argument 'decoding'`.

- [ ] **Step 4: Implement the decoding mode**

In `local.py`, add the import:

```python
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    ExtractionPayload,
    validate_extracted,
)
```

Add a `decoding` parameter to `__init__` (default `"schema"`), replacing the placeholder line from Task 2:

```python
        decoding: str = "schema",
```

```python
        if decoding not in ("schema", "json"):
            raise ValueError(f"unknown decoding mode: {decoding!r}")
        self._decoding = decoding
```

Add the module-level constant below `DEFAULT_MAX_OUTPUT_TOKENS`:

```python
# Generated once at import: it is a pure function of the models, and rebuilding
# it per call would put a schema walk inside a loop over every chunk.
_RESPONSE_SCHEMA = ExtractionPayload.model_json_schema()
```

In `_post_with_retries`, replace the `"format": "json",` line:

```python
            # A schema here is constrained decoding: the server masks any token
            # that would violate it, so an invalid modality or a missing field
            # cannot be emitted. The string "json" is the legacy mode and only
            # guarantees the output parses. Either way every item is still
            # validated by `validate_extracted` below — a hosted adapter may not
            # constrain at all, and behaviour has to match across adapters.
            "format": _RESPONSE_SCHEMA if self._decoding == "schema" else "json",
```

- [ ] **Step 5: Wire the setting through**

In `backend/src/policy_grapher/config.py`, below `extractor_model`:

```python
    # "schema" hands Ollama the JSON Schema and gets constrained decoding; "json"
    # is the legacy mode that only guarantees the output parses. Part of the cache
    # variant, so switching does not replay answers from the other mode.
    extractor_decoding: str = "schema"     # "schema" | "json"
```

In `build_extractor` in `extraction/__init__.py`, add to the `LocalExtractor(...)` call:

```python
            decoding=settings.extractor_decoding,
```

- [ ] **Step 6: Run the tests**

```bash
cd backend && uv run pytest tests/test_extraction_adapters.py -v
cd backend && uv run pytest -m "not integration"
```

Expected: PASS.

- [ ] **Step 7: Verify the server actually accepts the schema**

Pydantic emits `$defs`/`$ref` for the nested `ExtractedObligation` and `Modality`. Whether the runtime's grammar compiler handles those is a fact about the server, not something to assume.

```bash
cd backend && uv run python -c "
import json, httpx
from policy_grapher.extraction.schema import ExtractionPayload
r = httpx.post('http://localhost:11434/api/generate', timeout=600, json={
  'model': 'llama3.1:8b', 'stream': False,
  'format': ExtractionPayload.model_json_schema(),
  'prompt': 'The Director shall submit the report annually. Return obligations.',
  'options': {'temperature': 0, 'num_predict': 2048}})
r.raise_for_status(); print(json.dumps(json.loads(r.json()['response']), indent=2))
"
```

Expected: a parseable object with an `obligations` array. **If the server rejects `$ref`**, flatten the schema before sending — replace `_RESPONSE_SCHEMA` with an inlined literal built in `schema.py`, and record why in the ADR. Do not proceed to Task 4 until this command succeeds; Task 4's measurement is meaningless against a rejected schema.

- [ ] **Step 8: Commit**

```bash
git add backend/src/policy_grapher/extraction/ backend/src/policy_grapher/config.py backend/tests/test_extraction_adapters.py
git commit -m "feat: the model is constrained by the obligation schema, not asked for JSON"
```

---

### Task 4: Measure both modes against the gold set, and decide

One variable moves: `extractor_decoding`. Everything else — model, prompt version, runtime, gold set — is held.

**Files:**
- Modify: `backend/tests/test_obligation_ratchet.py:163-165`
- Create: `docs/specs/adr/ADR-037-the-model-is-constrained-by-the-schema.md`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: a recorded decision, and possibly raised floors in `FLOORS["local:llama3.1:8b"]`.

- [ ] **Step 1: Measure the legacy mode, twice, in separate processes**

Sprint 9 established that three runs inside one process prove less than they appear to. Two processes, and take the lower.

```bash
cd backend
EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b EXTRACTOR_DECODING=json \
  uv run pytest tests/test_obligation_ratchet.py::test_the_configured_extractor_clears_its_floors -v -rs
```

Run it a second time as a fresh process. Record `precision`, `recall`, `modality_accuracy` from the assertion output of each. If the gate passes, the scores are still printed on failure only — add `-s` and a temporary `print(overall)` if needed, or read them from the failure message by temporarily raising a floor.

- [ ] **Step 2: Measure the schema mode the same way**

```bash
cd backend
EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b EXTRACTOR_DECODING=schema \
  uv run pytest tests/test_obligation_ratchet.py::test_the_configured_extractor_clears_its_floors -v -rs
```

Twice, separate processes. **Do not run these concurrently with Step 1** — Ollama serialises and contention corrupts both.

- [ ] **Step 3: Write ADR-037 recording what was measured**

Create `docs/specs/adr/ADR-037-the-model-is-constrained-by-the-schema.md` following `docs/specs/adr/TEMPLATE-adr.md`. It must contain, with real numbers from Steps 1–2:

- **Context:** `format: "json"` is the legacy mode; it guarantees the output parses and enforces nothing else. Three measured costs: `modality: null` losing 8 chunks in 37 (2026-08-26); the sprint 11 repetition loop at 25 statements / 6 distinct; and the `"model output was not JSON"` rejection branch.
- **Decision:** constrained decoding is the default, with `"json"` retained as a switch because a hosted adapter may not support constraint and behaviour must stay comparable across adapters.
- **The measurement**, both modes, both processes, as a table.
- **Consequences:** name the outcome honestly. If schema mode scored *lower* on any leg, say so and say what was chosen anyway and why — the constraint tax is documented in the literature and a real result here is worth more than a tidy one.
- **Relationship to ADR-030:** the class of items ADR-030 allocates cost for mostly stops existing. ADR-030 is not superseded — it still governs items the Python-level validators refuse, such as the modality-word-in-statement rule, which no JSON Schema can express.

- [ ] **Step 4: Raise the floors if, and only if, both modes beat them**

Floors ratchet up. In `test_obligation_ratchet.py`, if the lower of the two schema-mode observations beats a recorded floor, raise it to that observation **truncated to three decimals, never rounded up**:

```python
FLOORS = {
    "local:llama3.1:8b": {"precision": 0.862, "recall": 0.892, "modality_accuracy": 0.85},
}
```

Add a dated comment block above `FLOORS` in the style the file already uses, recording the date, both modes, both processes, and which observation each floor was truncated from. **If schema mode scores below a floor, do not lower it** — that is a real regression and either the schema is wrong or the decision in ADR-037 is.

- [ ] **Step 5: Verify the gate passes on the shipped configuration**

```bash
cd backend && EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b \
  uv run pytest tests/test_obligation_ratchet.py -v -rs
```

Expected: PASS with no skips reported for the gate.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_obligation_ratchet.py docs/specs/adr/ADR-037-the-model-is-constrained-by-the-schema.md
git commit -m "docs: constrained decoding is measured against the gold set and recorded"
```

---

### Task 5: The extraction gate runs on every push

Finding 2. The gate has never run in CI: `extractor_adapter` defaults to `"null"`, `FLOORS` has no `"null"` key, so the test takes its first skip branch. Per the decision recorded for this work, CI runs the gate against `llama3.2:3b` per push.

**Files:**
- Modify: `backend/tests/test_obligation_ratchet.py` (`FLOORS`)
- Modify: `.github/workflows/ci.yml`
- Test: `backend/tests/test_ci.py`

**Interfaces:**
- Consumes: the pinned runtime string from Task 1; the shipped decoding mode from Task 4.
- Produces: `FLOORS["local:llama3.2:3b"]`.

- [ ] **Step 1: Pull the smaller model and measure it**

```bash
docker exec -it $(docker compose ps -q ollama) ollama pull llama3.2:3b
cd backend
EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.2:3b \
  uv run pytest tests/test_obligation_ratchet.py::test_the_configured_extractor_clears_its_floors -v -rs
```

Run twice in separate processes. Expect materially lower numbers than 8b — 3b is a smaller model and its floors are its own, not a weakened copy of 8b's.

- [ ] **Step 2: Record its floors**

In `test_obligation_ratchet.py`, add the second entry, with the lower observation of the two processes truncated:

```python
FLOORS = {
    "local:llama3.1:8b": {"precision": 0.862, "recall": 0.892, "modality_accuracy": 0.85},
    # Measured <DATE> against llama3.2:3b at temperature 0, decoding=schema, on
    # ollama <PINNED>, two separate processes. Lower observation, truncated.
    # These are CI's per-push floors: 3b is not the shipped model, it is the
    # smallest US-origin model (ADR-020) that makes the gate affordable on every
    # push. A regression that 3b cannot see is what the canary set is for.
    "local:llama3.2:3b": {"precision": 0.000, "recall": 0.000, "modality_accuracy": 0.000},
}
```

Replace the three zeros with the truncated measurements. **Do not copy 8b's numbers.**

- [ ] **Step 3: Write the failing CI test**

`backend/tests/test_ci.py` already asserts things about the workflow. Add:

```python
def test_ci_runs_the_extraction_gate_against_a_real_model():
    """The gate skips silently unless CI configures an adapter with floors.

    Before this, `extractor_adapter` defaulted to "null", FLOORS had no "null"
    key, and the gate took its first skip branch on every push — green because
    nothing checked, for the whole of DI-2.
    """
    workflow = WORKFLOW.read_text()
    assert "EXTRACTOR_ADAPTER: local" in workflow, (
        "CI does not configure a real extractor, so the extraction gate skips"
    )
    assert "llama3.2:3b" in workflow, "CI does not pull the model the gate needs"
```

`WORKFLOW` is already defined at `test_ci.py:24` as `REPO_ROOT / ".github" / "workflows" / "ci.yml"`. Reuse it; do not introduce a second path constant.

- [ ] **Step 4: Run it to verify it fails**

```bash
cd backend && uv run pytest tests/test_ci.py -v
```

Expected: FAIL — `CI does not configure a real extractor`.

- [ ] **Step 5: Add the job step**

In `.github/workflows/ci.yml`, in the `backend` job, **after** the "Integration tests" step:

```yaml
      # The extraction gate. Until this existed it skipped on every push:
      # `extractor_adapter` defaults to "null", FLOORS has no entry for "null",
      # and the test takes its first skip branch — so the gate on the product's
      # core value was green because nothing ran it. llama3.2:3b rather than the
      # shipped 8b because 2GB is affordable per push and 4.9GB is not; its
      # floors are its own, measured separately.
      - name: Start the pinned model runtime
        run: |
          docker run -d --name ollama -p 11434:11434 ollama/ollama:<PINNED>
          for _ in $(seq 1 60); do
            curl -sf http://localhost:11434/api/version && break
            sleep 2
          done
          docker exec ollama ollama pull llama3.2:3b

      - name: Extraction gate (real model)
        env:
          EXTRACTOR_ADAPTER: local
          EXTRACTOR_MODEL: llama3.2:3b
          EXTRACTOR_BASE_URL: http://localhost:11434
        # -rs prints skip reasons. A skip here means the gate did not run, which
        # is the failure this step exists to prevent — read the reason, do not
        # assume the tick means it passed.
        run: uv run pytest tests/test_obligation_ratchet.py -v -rs
```

- [ ] **Step 6: Run the tests**

```bash
cd backend && uv run pytest tests/test_ci.py tests/test_obligation_ratchet.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit and watch the real run**

```bash
git add backend/tests/test_obligation_ratchet.py backend/tests/test_ci.py .github/workflows/ci.yml
git commit -m "test: the extraction gate runs on every push, against a model with its own floors"
```

Push and read the CI log for the gate step. **Confirm it did not skip.** A green tick with `SKIPPED [1] THE EXTRACTION GATE DID NOT RUN` in the `-rs` output is the exact failure being fixed, and it will look like success.

---

### Task 6: A prompt change reports what it moved

Finding 3, and [STORY-107](../../backlog/stories/STORY-107-a-prompt-change-shows-its-blast-radius.md). Canary replay: a fixed, versioned set of real chunks, replayed and diffed against a recorded baseline. It needs no labels because it does not ask whether output is right — only whether it moved.

**Files:**
- Create: `backend/tests/canary/__init__.py`
- Create: `backend/tests/canary/replay.py`
- Create: `backend/tests/fixtures/canary/chunks.json`
- Create: `backend/tests/fixtures/canary/baseline.json`
- Create: `backend/tests/test_canary.py`

**Interfaces:**
- Consumes: Tasks 1–4 — the baseline is only meaningful once the runtime is pinned and the decoding mode is settled.
- Produces:
  - `select_canary_chunks(limit: int = 120) -> list[dict]` — deterministic sample of real chunks, each `{"chunk_id", "text", "section_path", "section_title"}`.
  - `record(extractor, chunks) -> dict` — `{chunk_id: [{"statement", "modality"}]}`, statements normalised.
  - `diff(baseline: dict, current: dict) -> dict` — `{"moved": [...], "added": [...], "removed": [...]}`.

- [ ] **Step 1: Build the canary chunk set**

Create `backend/tests/canary/replay.py`:

```python
"""Canary replay: what a prompt change moved, over real chunks, without labels.

The gold set asks whether an answer is right and needs eight hand-labelled
fixtures to do it. This asks a cheaper question that scales: did anything
change? Three sprints running, a prompt edit degraded an unrelated passage and
was caught only because the passage happened to be a fixture.

Deliberately not a pass/fail gate. A diff is information, not a regression —
most prompt changes are supposed to move something. What was missing was any
way to see the rest of what moved.
"""

import json
from pathlib import Path

from policy_grapher.chunking import chunk_pages
from policy_grapher.extraction.schema import normalize
from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "canary"


def select_canary_chunks(limit: int = 120) -> list[dict]:
    """A deterministic slice of the corpus: every sample PDF, chunks in order,
    round-robin across documents so no single document dominates the set.

    Deterministic because a canary set that varies between runs cannot tell a
    prompt change from a sampling change.
    """
    per_document: list[list[dict]] = []
    for path in sorted(SAMPLES.glob("*.pdf")):
        chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "section_path": chunk.section_path,
                "section_title": chunk.section_title,
            }
            for chunk in chunk_pages(pdf.extract_document(path).pages)
        ]
        per_document.append(chunks)

    out: list[dict] = []
    for index in range(max((len(c) for c in per_document), default=0)):
        for chunks in per_document:
            if index < len(chunks):
                out.append(chunks[index])
                if len(out) == limit:
                    return out
    return out
```

> **Verify before relying on this:** `chunk_pages` takes the pages of an extracted document. Confirm the exact call and the attribute holding pages by reading [`chunking.py`](../../../backend/src/policy_grapher/chunking.py) and [`sources/pdf.py`](../../../backend/src/policy_grapher/sources/pdf.py), and correct the two lines above to match. Do not guess the signature.

- [ ] **Step 2: Add record and diff**

Append to `backend/tests/canary/replay.py`:

```python
def record(extractor, chunks: list[dict]) -> dict:
    """What the extractor says about each chunk, in a form a diff can read.

    Statements are normalised with the same function obligation identity is
    hashed from, so a whitespace change is not reported as a moved duty. A chunk
    the extractor refuses records `None`, which is itself a signal: a chunk that
    starts or stops being rejected is one of the largest things a prompt edit
    can do.
    """
    out: dict[str, list[dict] | None] = {}
    for chunk in chunks:
        try:
            found = extractor.extract(
                chunk["text"],
                section_path=chunk["section_path"],
                section_title=chunk["section_title"],
            )
        except ValueError:
            out[chunk["chunk_id"]] = None
            continue
        out[chunk["chunk_id"]] = sorted(
            ({"statement": normalize(o.statement), "modality": str(o.modality)} for o in found),
            key=lambda item: item["statement"],
        )
    return out


def diff(baseline: dict, current: dict) -> dict:
    """Per chunk: what the baseline had, what the current run has, where they differ."""
    moved, added, removed = [], [], []
    for chunk_id in sorted(set(baseline) | set(current)):
        was, now = baseline.get(chunk_id, "absent"), current.get(chunk_id, "absent")
        if was == now:
            continue
        if was == "absent":
            added.append(chunk_id)
        elif now == "absent":
            removed.append(chunk_id)
        else:
            moved.append({"chunk_id": chunk_id, "was": was, "now": now})
    return {"moved": moved, "added": added, "removed": removed}
```

- [ ] **Step 3: Write the failing tests**

Create `backend/tests/test_canary.py`:

```python
from canary.replay import diff


def test_an_unchanged_run_reports_nothing():
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    assert diff(baseline, dict(baseline)) == {"moved": [], "added": [], "removed": []}


def test_a_changed_modality_is_reported_as_moved():
    """The failure this exists for: a duty still found, its force downgraded."""
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    current = {"c1": [{"statement": "the director shall report", "modality": "SHOULD"}]}
    assert diff(baseline, current)["moved"][0]["chunk_id"] == "c1"


def test_a_chunk_that_became_a_rejection_is_reported():
    """Sprint 11's repetition loop turned a working chunk into a rejection, and
    nothing outside the gold set would have shown it."""
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    assert diff(baseline, {"c1": None})["moved"][0]["now"] is None


def test_the_canary_set_is_deterministic():
    from canary.replay import select_canary_chunks

    assert [c["chunk_id"] for c in select_canary_chunks(40)] == [
        c["chunk_id"] for c in select_canary_chunks(40)
    ]
```

- [ ] **Step 4: Run them to verify they fail, then pass**

```bash
cd backend && uv run pytest tests/test_canary.py -v
```

Expected: FAIL first (module missing), PASS once Steps 1–2 are in place. `test_the_canary_set_is_deterministic` reads real PDFs and is slower; if it needs the `integration` marker to stay out of the fast suite, add it.

- [ ] **Step 5: Record the baseline**

Only now — after Tasks 1–4, so the baseline is taken against a pinned runtime and the settled decoding mode.

```bash
cd backend && EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b uv run python -c "
import json, sys
from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor
sys.path.insert(0, 'tests')
from canary.replay import FIXTURES, record, select_canary_chunks
chunks = select_canary_chunks(120)
FIXTURES.mkdir(parents=True, exist_ok=True)
(FIXTURES / 'chunks.json').write_text(json.dumps(chunks, indent=2))
(FIXTURES / 'baseline.json').write_text(
    json.dumps(record(build_extractor(Settings()), chunks), indent=2))
print(f'baseline recorded over {len(chunks)} chunks')
"
```

This is a long model-bound run. **Start nothing else model-bound while it runs.**

- [ ] **Step 6: Add the header that says what the baseline is of**

Prepend a `_meta` key to `baseline.json` recording the date, `PROMPT_VERSION`, model, decoding mode, and the pinned runtime version. A baseline that cannot say what produced it is a number without a denominator — the failure sprint 11 opened with.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/canary/ backend/tests/test_canary.py backend/tests/fixtures/canary/
git commit -m "feat: a prompt change can be replayed over real chunks and diffed"
```

---

### Task 7: Standing actions get a living home

Finding 4. Roughly eight standing actions live only in frozen retrospectives, which CONVENTIONS correctly forbids editing — so a rule is discoverable only by reading three dated documents and knowing which supersede each other.

**Files:**
- Create: `docs/sprints/standing-actions.md`
- Modify: `docs/sprints/README.md`
- Modify: `docs/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the canonical list of standing actions.

> **A note on the markdown below.** `scaffold.py check` matches markdown links
> with a regex and does not skip fenced blocks, so literal link syntax inside
> this plan would be resolved relative to `docs/superpowers/plans/` and reported
> broken forever. The content below therefore names link targets in prose rather
> than embedding them. Where it says *link the text X to `path`*, write an
> ordinary markdown link — the target is given exactly and nothing is left to
> choose.

- [ ] **Step 1: Write the living document**

Create `docs/sprints/standing-actions.md` with exactly this content:

```markdown
# Standing actions

*Living document — edit in place. Last reviewed: 2026-08-31*

Working practices adopted at a retrospective and still in force. The
retrospective that adopted each one owns the story of *why* and stays frozen;
this document owns *what is currently true*, so a rule can be corrected without
editing a dated record.

Retiring a rule means deleting its row here and saying so in the next
retrospective. A rule that turns out to be wrong is corrected here — sprint 11
found that a standing action inherits the errors of the measurement it came
from, so these are revisable, not scripture.

| Action | Adopted |
| --- | --- |
| When a new test passes on its first run, mutate the thing it guards before believing it. Mutate by keeping a copy of the file, never by reverting it. | Sprints 8, 9 |
| When a gate goes red after an interface changed, check the gate calls the new interface before believing what it says about the thing behind it. | Sprint 9 |
| When a guard requires a field to be present, assume a model will find the cheapest way to fill it. | Sprint 9 |
| Set a floor from the lowest observation across processes, truncated, never rounded to a single run. | Sprint 9 |
| An anomaly is a hypothesis about the measurement first and about the system second — check it with the code's own function. | Sprint 10 |
| Change one thing when a number is going to be read from it. | Sprint 10 |
| Order rule changes before the long-running job they invalidate. | Sprint 10 |
| Verify a denominator before quoting a ratio against it. | Sprint 11 |
| A conclusion inherits the errors of the measurement it came from — re-check both. | Sprint 11 |
| One model-bound job at a time. | Sprint 11 |

Each sprint's retrospective is in its own folder here — `sprint-09/retrospective.md`
and so on — and is where the reasoning behind its rows was written down.

The two rules in `AGENTS.md` at the repository root — never close an unfinished
sprint, never leave a known bug unfixed — are the project owner's and are not
revisable here.
```

Check each row against its retrospective before committing; transcribe rather than paraphrase from memory.

- [ ] **Step 2: Link it from the sprints index**

In `docs/sprints/README.md`, after the "Ceremonies, briefly" section, add a `## Standing actions` heading followed by this sentence, with the text *standing-actions.md* linked to `standing-actions.md`:

> Practices adopted at a retrospective and still in force are listed in
> standing-actions.md. Retrospectives stay frozen; that document is where the
> current set lives and where a wrong one gets corrected.

- [ ] **Step 3: Add it to the canonical table**

In `docs/README.md`, add one row to the "Canonical documents" table, immediately after the "What are we doing right now?" row. The left cell is `How do we work?`. The right cell links the text *Sprint cadence* to `sprints/README.md` and the text *standing actions* to `sprints/standing-actions.md`, joined by the word "and".

- [ ] **Step 4: Verify links resolve**

```bash
python ~/.claude/skills/synced/project-docs-init/scripts/scaffold.py check --root .
```

Expected: `No unfilled placeholders.` and `No broken relative links.`

- [ ] **Step 5: Commit**

```bash
git add docs/sprints/standing-actions.md docs/sprints/README.md docs/README.md
git commit -m "docs: standing actions have a living home instead of three frozen ones"
```

---

### Task 8: Record the scope in the backlog and close out

**Files:**
- Modify: `docs/backlog/backlog.md`
- Modify: `docs/specs/architecture.md`

- [ ] **Step 1: Add the backlog rows**

Highest existing ID is STORY-108, so these are 109–112. Add to the **Done** table with sprint 12, phrased as outcomes, keeping the ID column permanent:

- `STORY-109` — The model runtime is pinned, so a floor measures something repeatable
- `STORY-110` — The model is constrained by the obligation schema rather than asked for JSON
- `STORY-111` — The extraction gate runs on every push
- `STORY-112` — A prompt change can be replayed over real chunks and diffed

- [ ] **Step 2: Update the architecture doc**

`specs/architecture.md` is living and describes today. Two edits, describing state rather than narrating the change:

- In **Components**, the backend row: note that the extractor is handed a JSON Schema and the runtime is pinned.
- In **Known weak points**, replace nothing — *add* an entry recording that the extraction prompt has non-local effects on an 8B model, that the canary set is what detects them, and what it does not cover. Then refresh the *Last reviewed* date.

- [ ] **Step 3: Run everything**

```bash
cd backend && uv run pytest
cd frontend && docker compose run --rm frontend npm test
python ~/.claude/skills/synced/project-docs-init/scripts/scaffold.py check --root .
```

Expected: all green, no broken links, and **no skip reported for the extraction gate**.

- [ ] **Step 4: Commit**

```bash
git add docs/backlog/backlog.md docs/specs/architecture.md
git commit -m "docs: sprint 12 records the extraction work it took on"
```

- [ ] **Step 5: Do not close the sprint here**

Sprint 12 committed STORY-106 and STORY-107 before this work was added. Walk the [Definition of Done](../../backlog/README.md#definition-of-done) literally against **every** committed item before writing `review.md`. If STORY-106 is unmet, the sprint stays open — that is the first standing rule in `AGENTS.md` and it is not a judgement call. The added scope is recorded in `review.md` when the sprint genuinely closes.

---

## Notes on sequencing

Task 1 before everything: it is the control every later measurement rests on. Task 2 before Task 3, or the cache serves Task 3 answers from the legacy mode and the measurement is of nothing. Task 4 before Task 6, or the canary baseline is recorded against a decoding mode that is about to change — the sprint 10 action about ordering rule changes before the long jobs they invalidate, applied to the longest job in this plan.

Tasks 7 and 8 touch no code and can be done at any point.
