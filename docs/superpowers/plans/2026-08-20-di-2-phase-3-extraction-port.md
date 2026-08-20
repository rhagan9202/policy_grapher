# DI-2 Phase 3: Obligation Extraction Port — Implementation Plan

**Status:** Complete. Verified on 2026-08-20 with `uv run pytest` (378 passed), including the integration suite against a real `neo4j:2025.10` container.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn stored text into `:Obligation` nodes anchored to the chunk they came from — behind a provider-agnostic port, with an eval ratchet that makes a provider swap a tested property rather than a hope.

**Architecture:** An `ObligationExtractor` port takes a chunk and returns validated obligations. A local small model is the default adapter; a hosted provider is swappable behind the same contract. **Schema validation lives in our code, on every adapter** — native constrained decoding is an optimisation, never the correctness boundary. A gold-set ratchet pins precision, recall and modality accuracy per adapter.

**Tech Stack:** FastAPI, Pydantic v2, `httpx`, neo4j Python driver 6.x, pytest + testcontainers, a local instruct model served over HTTP.

**Spec:** [`docs/superpowers/specs/2026-08-20-di-2-design.md`](../specs/2026-08-20-di-2-design.md) — see *Extraction*.

**Depends on:** Phase 2 — `:Chunk` nodes exist with `page` and `section_path`.

## Global Constraints

- Python `>=3.14`; deps via `uv`. **This phase adds exactly one runtime dependency: `httpx`** (already a dev dep; promote it). Add nothing else.
- Ruff enforced **as a test**. Integration tests use real `neo4j:2025.10`; never mock the driver.
- **The default adapter must require no running model.** `uv run pytest` has to pass on a machine with no model server, or the suite becomes unrunnable in CI and on a fresh clone.
- `:Obligation` is **derived** — droppable, rebuildable, never hand-edited.
- Obligation identity is `hash(version_id, section_path, normalized_statement)` and must be stable across re-extraction. Get this wrong and Phase 4's human decisions are orphaned on every rebuild.
- The deterministic regex extractor in `sources/pdf.py` is **untouched**. SPEC-001 requires citation extraction to stay model-free; obligation extraction is an additive second path over stored text.
- Documentation updated in the same change.

## Decisions an executor must not silently change

**1. Validation is ours, not the provider's.** A Pydantic model validates every extraction result on every adapter. A hosted provider's JSON-schema mode and a local runtime's grammar are both optimisations *behind* that boundary. This is what makes the swap behaviour-preserving.

**2. `modality` is a closed enum and its own ratchet floor.** `SHALL | MUST | SHOULD | MAY`. A `SHALL` misread as `SHOULD` silently downgrades a binding obligation to advice, and an aggregate F1 hides it. It gets a separate floor.

**3. Extraction is cached by content.** Key: `(chunk_id, adapter_id, prompt_version)`.
*Executor's note (2026-08-20):* implemented as `(sha256(section_path + chunk_text), adapter_id, prompt_version)`, following the design spec's `chunk_content_hash` rather than this line's `chunk_id`, on the project owner's decision. A chunk id hashes *where* a chunk sits and deliberately not its text (ADR-012), so keying on it would let a re-chunk reuse an id over different words and be answered from text that no longer exists — the exact staleness this decision exists to prevent. `section_path` stays in the key because it is rendered into the prompt. See [ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md). Rebuilds are then cheap and adapter comparisons are like-for-like. A prompt change is a `prompt_version` bump — never an in-place edit, or the cache silently serves results from a prompt that no longer exists.

**4. Confidence is recorded, never used to filter here.** Phase 4's review queue decides what a human sees. An extractor that silently drops low-confidence obligations hides its own failures.

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/src/policy_grapher/extraction/__init__.py` | *Create* — the port and its result types |
| `backend/src/policy_grapher/extraction/schema.py` | *Create* — `ExtractedObligation`, `Modality`, obligation identity |
| `backend/src/policy_grapher/extraction/prompt.py` | *Create* — the extraction prompt and its version |
| `backend/src/policy_grapher/extraction/local.py` | *Create* — local HTTP model adapter |
| `backend/src/policy_grapher/extraction/null.py` | *Create* — default adapter; extracts nothing |
| `backend/src/policy_grapher/extraction/cache.py` | *Create* — content-keyed result cache |
| `backend/src/policy_grapher/obligations.py` | *Create* — writing obligations to the graph |
| `backend/src/policy_grapher/db.py` | *Modify* — obligation constraint |
| `backend/src/policy_grapher/config.py` | *Modify* — adapter settings |
| `backend/tests/fixtures/gold/*.json` | *Create* — hand-labelled gold obligations |
| `backend/tests/test_obligation_ratchet.py` | *Create* — the swap gate |

---

### Task 1: The port, the schema, and identity

**Files:**
- Create: `backend/src/policy_grapher/extraction/{__init__,schema}.py`, `backend/tests/test_extraction_schema.py`

**Interfaces:**
- Produces: `Modality` (StrEnum), `ExtractedObligation` (Pydantic), `obligation_id(version_id, section_path, statement) -> str`, and the `ObligationExtractor` protocol:
  `extract(chunk_text: str, *, section_path: list[str]) -> list[ExtractedObligation]`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_extraction_schema.py`:

```python
import pytest
from pydantic import ValidationError

from policy_grapher.extraction.schema import ExtractedObligation, Modality, obligation_id


def test_a_well_formed_obligation_validates():
    o = ExtractedObligation(
        statement="The Director shall notify the Comptroller within 24 hours.",
        modality=Modality.SHALL,
        actor="The Director",
        deadline="24 hours",
        conditions=None,
        confidence=0.9,
    )
    assert o.modality is Modality.SHALL


def test_an_unknown_modality_is_rejected():
    """A closed enum: an adapter inventing 'WILL' must fail loudly, not silently."""
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality="WILL", actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_confidence_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=1.4,
        )


def test_an_empty_statement_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="   ", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_identity_is_stable_across_runs():
    args = ("v", ["3", "3.2"], "The Director shall notify the Comptroller.")
    assert obligation_id(*args) == obligation_id(*args)


def test_identity_ignores_whitespace_and_case_in_the_statement():
    """Re-extraction must not orphan a human decision over a reflowed line."""
    a = obligation_id("v", ["3.2"], "The Director shall notify.")
    b = obligation_id("v", ["3.2"], "the  director   SHALL notify.")
    assert a == b


def test_identity_distinguishes_sections():
    a = obligation_id("v", ["3.2"], "Same words.")
    b = obligation_id("v", ["4.1"], "Same words.")
    assert a != b


def test_identity_distinguishes_versions():
    a = obligation_id("v1", ["3.2"], "Same words.")
    b = obligation_id("v2", ["3.2"], "Same words.")
    assert a != b
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_extraction_schema.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Implement the schema**

Create `backend/src/policy_grapher/extraction/schema.py`:

```python
"""What an extracted obligation is, and how it is identified.

Validation lives here rather than at a provider boundary on purpose: a local
runtime's grammar and a hosted provider's JSON-schema mode are optimisations,
and the contract has to hold identically on both or the port is not a port.
"""

import hashlib
import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

WHITESPACE = re.compile(r"\s+")


class Modality(StrEnum):
    """How binding an obligation is.

    Closed on purpose. SHALL misread as SHOULD downgrades a binding duty to
    advice, silently — so an adapter that invents a value must fail loudly.
    """

    SHALL = "SHALL"
    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"


class ExtractedObligation(BaseModel):
    statement: str = Field(min_length=1)
    modality: Modality
    actor: str | None
    deadline: str | None
    conditions: str | None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("statement")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("statement must not be blank")
        return value


def normalize(statement: str) -> str:
    """The form identity is computed over.

    Case and whitespace only. A reflowed line or a changed indent must not
    orphan a human decision, but a changed *word* must — that is a different
    obligation, and Phase 5 needs to see it as one.
    """
    return WHITESPACE.sub(" ", statement).strip().casefold()


def obligation_id(version_id: str, section_path: list[str], statement: str) -> str:
    key = f"{version_id}|{'/'.join(section_path)}|{normalize(statement)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
```

Create `backend/src/policy_grapher/extraction/__init__.py`:

```python
"""Obligation extraction, behind a provider-agnostic port."""

from typing import Protocol

from policy_grapher.extraction.schema import ExtractedObligation


class ObligationExtractor(Protocol):
    """The contract every adapter meets.

    `adapter_id` participates in the cache key, so it must change whenever the
    thing behind it changes — model, quantisation, or provider.
    """

    adapter_id: str

    def extract(
        self, chunk_text: str, *, section_path: list[str]
    ) -> list[ExtractedObligation]: ...
```

- [x] **Step 4: Run tests, then commit**

Run: `cd backend && uv run pytest tests/test_extraction_schema.py -v`
Expected: PASS (8 tests)

```bash
git add backend/src/policy_grapher/extraction backend/tests/test_extraction_schema.py
git commit -m "feat: an obligation has a schema and a permanent identity"
```

---

### Task 2: The null and local adapters

**Files:**
- Create: `backend/src/policy_grapher/extraction/{null,local,prompt}.py`, `backend/tests/test_extraction_adapters.py`
- Modify: `backend/src/policy_grapher/config.py`, `backend/pyproject.toml`

**Interfaces:**
- Produces: `NullExtractor` (`adapter_id = "null"`), `LocalExtractor(base_url, model)` (`adapter_id = f"local:{model}"`), `EXTRACTION_PROMPT`, `PROMPT_VERSION`, and `build_extractor(settings) -> ObligationExtractor`

- [x] **Step 1: Write the failing tests**

Create `backend/tests/test_extraction_adapters.py`:

```python
import json

import httpx
import pytest

from policy_grapher.config import Settings
from policy_grapher.extraction.local import LocalExtractor
from policy_grapher.extraction.null import NullExtractor
from policy_grapher.extraction import build_extractor


def test_the_null_adapter_extracts_nothing():
    assert NullExtractor().extract("The Director shall act.", section_path=["1"]) == []


def test_the_default_adapter_needs_no_model_server():
    """The suite must run on a machine with no model. Default is null."""
    assert build_extractor(Settings(_env_file=None)).adapter_id == "null"


def test_the_local_adapter_parses_a_well_formed_response():
    payload = {
        "obligations": [
            {
                "statement": "The Director shall notify the Comptroller.",
                "modality": "SHALL",
                "actor": "The Director",
                "deadline": None,
                "conditions": None,
                "confidence": 0.88,
            }
        ]
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": json.dumps(payload)})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    result = extractor.extract("...", section_path=["3.2"])
    assert len(result) == 1
    assert result[0].modality == "SHALL"


def test_a_response_failing_our_schema_is_rejected_not_coerced():
    """Our validation is the correctness boundary, whatever the provider did."""
    payload = {"obligations": [{"statement": "x", "modality": "WILL", "confidence": 2}]}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": json.dumps(payload)})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    with pytest.raises(ValueError, match="did not match the obligation schema"):
        extractor.extract("...", section_path=["3.2"])


def test_unparseable_output_is_rejected_loudly():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": "I think there are none!"})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    with pytest.raises(ValueError):
        extractor.extract("...", section_path=["3.2"])


def test_an_empty_obligation_list_is_a_valid_answer():
    """Most chunks carry no obligation. That is not a failure."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": json.dumps({"obligations": []})})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )
    assert extractor.extract("Table of contents.", section_path=["1"]) == []


def test_the_adapter_id_names_the_model():
    """It is part of the cache key — two models must not share cached results."""
    assert LocalExtractor(base_url="http://m", model="qwen3:8b").adapter_id == "local:qwen3:8b"
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_extraction_adapters.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [x] **Step 3: Promote `httpx` to a runtime dependency**

In `backend/pyproject.toml`, move `httpx>=0.28` from the dev group into `dependencies`.
It is now used by shipped code, so its dev-only placement would be wrong.

- [x] **Step 4: Write the prompt**

Create `backend/src/policy_grapher/extraction/prompt.py`:

```python
"""The extraction prompt, and its version.

PROMPT_VERSION participates in the cache key. Bump it whenever the prompt text
changes — an in-place edit would leave the cache serving results produced by a
prompt that no longer exists, which is invisible and very hard to debug.
"""

PROMPT_VERSION = 1

EXTRACTION_PROMPT = """\
You are extracting obligations from a passage of policy text.

An obligation is a duty the text places on someone: who must do what, by when,
under what conditions. Extract only what the passage states. Do not infer a
duty that is not written, and do not restate background, definitions, or
purpose statements as obligations.

modality must be exactly one of SHALL, MUST, SHOULD, MAY — the word the passage
actually uses. If the passage says "shall", the modality is SHALL even if you
would phrase it differently. This distinction is load-bearing: SHALL and MUST
bind, SHOULD and MAY do not.

Most passages contain no obligation at all. Returning an empty list is a
correct and common answer. Do not manufacture one to seem useful.

Set confidence to how certain you are that this is a real, stated obligation.

Section: {section_path}

Passage:
{chunk_text}

Respond with JSON only, matching this shape:
{{"obligations": [{{"statement": "...", "modality": "SHALL", "actor": "...",
  "deadline": null, "conditions": null, "confidence": 0.0}}]}}
"""
```

- [x] **Step 5: Implement both adapters**

Create `backend/src/policy_grapher/extraction/null.py`:

```python
"""The adapter that extracts nothing.

The default, so `uv run pytest` passes on a machine with no model server. A
suite that cannot run without infrastructure stops being run.
"""

from policy_grapher.extraction.schema import ExtractedObligation


class NullExtractor:
    adapter_id = "null"

    def extract(
        self, chunk_text: str, *, section_path: list[str]
    ) -> list[ExtractedObligation]:
        return []
```

Create `backend/src/policy_grapher/extraction/local.py`:

```python
"""A local model served over HTTP (Ollama-compatible).

Constrained decoding via the server's JSON mode is requested where available,
but it is an optimisation: every response is validated against our own schema
regardless, because that is what keeps behaviour identical across adapters.
"""

import json

import httpx
from pydantic import ValidationError

from policy_grapher.extraction.prompt import EXTRACTION_PROMPT
from policy_grapher.extraction.schema import ExtractedObligation

TIMEOUT_SECONDS = 120.0


class LocalExtractor:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(transport=transport, timeout=TIMEOUT_SECONDS)

    @property
    def adapter_id(self) -> str:
        return f"local:{self._model}"

    def extract(
        self, chunk_text: str, *, section_path: list[str]
    ) -> list[ExtractedObligation]:
        response = self._client.post(
            f"{self._base_url}/api/generate",
            json={
                "model": self._model,
                "prompt": EXTRACTION_PROMPT.format(
                    section_path="/".join(section_path), chunk_text=chunk_text
                ),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        response.raise_for_status()
        raw = response.json()["response"]

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model output was not JSON: {raw[:200]!r}") from exc

        try:
            return [
                ExtractedObligation.model_validate(item)
                for item in payload.get("obligations", [])
            ]
        except ValidationError as exc:
            raise ValueError(
                f"model output did not match the obligation schema: {exc}"
            ) from exc
```

- [x] **Step 6: Add settings and the factory**

In `config.py`, inside `Settings`:

```python
    extractor_adapter: str = "null"          # "null" | "local"
    extractor_model: str = "qwen3:8b"
    extractor_base_url: str = "http://localhost:11434"
```

Append to `extraction/__init__.py`:

```python
def build_extractor(settings: "Settings") -> ObligationExtractor:
    """Resolve the configured adapter. Unknown names fail at startup, not mid-ingest."""
    from policy_grapher.extraction.local import LocalExtractor
    from policy_grapher.extraction.null import NullExtractor

    if settings.extractor_adapter == "null":
        return NullExtractor()
    if settings.extractor_adapter == "local":
        return LocalExtractor(
            base_url=settings.extractor_base_url, model=settings.extractor_model
        )
    raise ValueError(f"unknown extractor adapter: {settings.extractor_adapter!r}")
```

- [x] **Step 7: Run tests and commit**

Run: `cd backend && uv run pytest tests/test_extraction_adapters.py -v` then the full suite.
Expected: PASS

```bash
git add backend/src/policy_grapher/extraction backend/src/policy_grapher/config.py \
        backend/pyproject.toml backend/uv.lock backend/tests/test_extraction_adapters.py
git commit -m "feat: extraction has a port, a null default and a local adapter"
```

---

### Task 3: Content-keyed cache and obligations in the graph

**Files:**
- Create: `backend/src/policy_grapher/extraction/cache.py`, `backend/src/policy_grapher/obligations.py`, `backend/tests/test_obligations.py`
- Modify: `backend/src/policy_grapher/db.py`

**Interfaces:**
- Produces: `cache_key(chunk_id, adapter_id, prompt_version) -> str`, `CachedExtractor(inner, store)`, `write_obligations(tx, *, version_id, chunk_id, section_path, obligations) -> int`, `drop_obligations(tx, *, version_id) -> int`

- [x] **Step 1: Add the constraint**

In `db.py`, append to `CONSTRAINTS`:

```python
    (
        "CREATE CONSTRAINT obligation_id_unique IF NOT EXISTS "
        "FOR (o:Obligation) REQUIRE o.obligation_id IS UNIQUE"
    ),
```

- [x] **Step 2: Write the failing tests**

Create `backend/tests/test_obligations.py` covering:
- `cache_key` changes when the adapter changes, when the prompt version changes, and when the chunk changes — three separate tests, because a key that ignores any one of them serves stale results silently
- a `CachedExtractor` calls its inner extractor once for two identical requests
- `write_obligations` creates `(:DocumentVersion)-[:MANDATES]->(:Obligation)-[:ANCHORED_IN]->(:Chunk)`
- writing the same obligations twice creates nothing new (deterministic ids)
- `drop_obligations` removes obligations and leaves chunks and versions standing
- an obligation whose statement changed gets a **different** id, so Phase 5 sees it as modified

Write each as a real test with assertions, following the shape used in `test_chunks.py`.

- [x] **Step 3: Run to verify failure, then implement**

`cache.py` wraps any `ObligationExtractor` and memoises by `cache_key`. Back it with a
simple table in Neo4j (`:ExtractionCache {key, payload_json}`) rather than an in-process
dict, so a rebuild across process restarts is still cheap.

`obligations.py` mirrors `chunks.py`: a `MERGE` on `obligation_id` with `ON CREATE SET`,
`MANDATES` from the version, `ANCHORED_IN` to the chunk, and a `DETACH DELETE` drop scoped
to one version.

- [x] **Step 4: Run tests, full suite, commit**

```bash
git add backend/src/policy_grapher backend/tests/test_obligations.py
git commit -m "feat: obligations land in the graph, anchored to their chunk"
```

---

### Task 4: The eval ratchet

**Files:**
- Create: `backend/tests/fixtures/gold/*.json`, `backend/tests/test_obligation_ratchet.py`
- Create: `docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md`

**Interfaces:**
- Produces: `score(predicted, gold) -> dict` with `precision`, `recall`, `modality_accuracy`

This task is the reason the phase is trustworthy. Without it, an adapter swap is a hope.

- [x] **Step 1: Build the gold set**

Hand-label obligations for **three** passages drawn from `data/samples/` PDFs — one dense
in `SHALL`, one mostly definitional (so the correct answer is nearly empty), and one mixing
modalities. Each fixture is a JSON file: the chunk text, its `section_path`, and the list of
obligations a careful reader would extract.

Labelling is the work here. Do it by reading the passage, not by running an extractor and
correcting it — a gold set derived from a model's output cannot measure that model.

- [x] **Step 2: Write the scorer and its tests**

Matching is on `normalize(statement)`, so wording is compared the way identity is.
`modality_accuracy` is computed **only over matched pairs** — it answers "when we found the
obligation, did we get its force right?", which is the question that matters. Test the
scorer itself against hand-built cases: perfect match, a miss, a false positive, and a
correct statement with the wrong modality.

- [x] **Step 3: Write the ratchet test**

```python
FLOORS = {
    # Per adapter. The local model is for iteration speed; a hosted adapter must
    # clear the production bar before it is promoted. Raise a floor when a run
    # beats it — never lower one to make a red suite green.
    "null": {"precision": 0.0, "recall": 0.0, "modality_accuracy": 0.0},
    "local:qwen3:8b": {"precision": 0.60, "recall": 0.50, "modality_accuracy": 0.85},
}
```

The test skips when the configured adapter has no floors recorded, and **fails loudly** if
a configured adapter scores below its floor. Mark it `@pytest.mark.integration` and skip it
when the model server is unreachable — but make the skip message say plainly that the gate
did not run, so a green suite is never mistaken for a passed gate.

- [x] **Step 4: Write ADR-013**

Must state: the LLM is a port, not a dependency; validation lives in our code on every
adapter and why; the cache key includes adapter and prompt version, and a prompt change is
a version bump; `modality` gets its own floor because an aggregate hides the error that
matters; and the ratchet is the swap gate — "swappable" is a tested property, and floors
ratchet up only.

- [x] **Step 5: Run everything and commit**

```bash
git add backend/tests docs/specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md
git commit -m "feat: extraction quality is a ratchet, and the swap is a gate"
```

---

## Done when

- `uv run pytest` passes on a machine with **no model server** (default adapter is null)
- The local adapter extracts obligations from a real passage and they land anchored to their chunk
- Re-extraction reproduces identical obligation ids
- The cache calls the model once for two identical requests, and misses when the adapter or prompt version changes
- The ratchet fails when an adapter scores below its floor, and says so when it did not run
- ADR-013 exists

Phase 4 (typed links and the review queue) can start.
