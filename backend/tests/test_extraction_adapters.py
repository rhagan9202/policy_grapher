import json
from pathlib import Path

import httpx
import pytest

from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor
from policy_grapher.extraction.local import LocalExtractor
from policy_grapher.extraction.null import NullExtractor
from policy_grapher.extraction.prompt import EXTRACTION_PROMPT, PROMPT_VERSION


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

    result = extractor.extract(PASSAGE, section_path=["3.2"])
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
        extractor.extract(PASSAGE, section_path=["3.2"])


def test_unparseable_output_is_rejected_loudly():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": "I think there are none!"})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    with pytest.raises(ValueError):
        extractor.extract(PASSAGE, section_path=["3.2"])


def test_an_empty_obligation_list_is_a_valid_answer():
    """Most chunks carry no obligation. That is not a failure."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"response": json.dumps({"obligations": []})}
        )
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )
    assert extractor.extract("Table of contents.", section_path=["1"]) == []


def test_the_adapter_id_names_the_model():
    """It is part of the cache key — two models must not share cached results."""
    assert (
        LocalExtractor(base_url="http://m", model="llama3.1:8b").adapter_id
        == "local:llama3.1:8b"
    )


def test_the_runtime_version_is_fetched_once_and_remembered():
    """Lazily fetched, then cached — a chunk-by-chunk rebuild must not hit
    /api/version once per chunk."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"version": "0.32.15"})

    extractor = LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    assert extractor.runtime_version == "0.32.15"
    assert extractor.runtime_version == "0.32.15"
    assert calls["n"] == 1


def test_the_runtime_version_falls_back_to_unknown_when_the_server_will_not_say():
    """A cache that degrades to over-keying is safe; failing extraction because
    a version endpoint is missing is not."""
    extractor = LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(404, text="not found")
        ),
    )

    assert extractor.runtime_version == "unknown"


def test_the_cache_variant_combines_decoding_and_runtime_version():
    """Both halves of what silently varied a model's answer end up in the
    variant the cache key is widened with."""
    extractor = LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"version": "0.32.15"})
        ),
    )

    assert extractor.cache_variant == "json@0.32.15"


def test_an_unknown_adapter_name_fails_loudly():
    """Better at startup than mid-ingest, halfway through a document."""
    with pytest.raises(ValueError, match="unknown extractor adapter"):
        build_extractor(Settings(_env_file=None, extractor_adapter="gpt-9"))


# --- the per-call timeout (STORY-058) -----------------------------------------


def test_the_extractor_timeout_is_configurable():
    """Found by sprint 4's walkthrough: a rebuild died on chunk 1 of 34 with
    httpx.ReadTimeout against a CPU-only host measured at ~7 tokens/second.

    `rebuild_job_timeout_seconds` is a setting whose comment
    says a real-model rebuild admits no short timeout that is not a false alarm.
    That reasoning applies to the HTTP call inside the job just as much.
    """
    from policy_grapher.config import Settings

    settings = Settings(_env_file=None, extractor_timeout_seconds=42.0)

    assert settings.extractor_timeout_seconds == 42.0


def test_the_default_extractor_timeout_survives_cpu_inference():
    """A default a CPU host can actually meet. 120s could not."""
    from policy_grapher.config import Settings

    assert Settings(_env_file=None).extractor_timeout_seconds >= 600.0


def test_the_configured_timeout_reaches_the_http_client():
    """A setting nothing reads is not a fix."""
    from policy_grapher.config import Settings
    from policy_grapher.extraction import build_extractor

    extractor = build_extractor(
        Settings(
            _env_file=None, extractor_adapter="local", extractor_timeout_seconds=37.0
        )
    )

    assert extractor._client.timeout.read == 37.0


# --- the job timeout (found by the 2026-08-25 walkthrough) ---------------------

# Measured on CPU and written into the README: "~104 seconds a chunk … so 34
# chunks is around an hour". The number is the whole argument for the assertion
# below, so it is named rather than folded into a magic total.
MEASURED_SECONDS_PER_CHUNK = 104


def test_the_job_timeout_outlasts_the_largest_edition_in_the_corpus():
    """The defect this pins, found by running a real rebuild end to end.

    `rebuild_job_timeout_seconds` defaulted to 1800 — thirty minutes — while the
    README documented a rebuild as roughly an hour for 34 chunks and every
    edition in `data/samples` is larger than seventeen chunks. A real run of
    DoDD 5000.01's 2020 edition died at chunk 30 of 37 with
    `JobTimeoutException`, reported `counts: {}`, and wrote no obligations.

    The per-call `extractor_timeout_seconds` was raised for exactly this reason
    in sprint 4, reasoning *from* this setting's own comment — and nobody
    checked whether this setting survived the same argument. It did not.
    """
    from policy_grapher.chunking import chunk_pages
    from policy_grapher.config import Settings
    from policy_grapher.sources.pdf import pages_of

    samples = Path(__file__).resolve().parents[2] / "data" / "samples"
    largest = max(
        len(chunk_pages(pages_of(path), version_id=path.stem))
        for path in samples.glob("*.pdf")
    )
    needed = largest * MEASURED_SECONDS_PER_CHUNK

    assert Settings(_env_file=None).rebuild_job_timeout_seconds >= needed, (
        f"the largest edition in data/samples is {largest} chunks, which at "
        f"{MEASURED_SECONDS_PER_CHUNK}s a chunk needs {needed}s; a rebuild of it "
        "cannot finish inside the configured job timeout"
    )


def test_the_result_outlives_the_run_that_produced_it():
    """`rebuild_result_ttl_seconds` carries a comment claiming it is "much longer
    than the timeout, deliberately" — the result being the only record of what a
    run produced, and an expired one answering 404 indistinguishably from a run
    id that never existed. Nothing checked that claim, so raising the job
    timeout could have quietly inverted it.
    """
    settings = Settings(_env_file=None)

    assert settings.rebuild_result_ttl_seconds > settings.rebuild_job_timeout_seconds


# --- transient transport failures (found by the 2026-08-26 rebuild) -----------


def test_a_transient_server_error_is_retried_rather_than_ending_the_run():
    """A 37-chunk rebuild died at chunk 24 on a single 500 from Ollama, which was
    healthy again seconds later and had served twenty-three calls before it.

    That is the same shape ADR-023 already settled for a chunk whose output fails
    the schema — one bad item costs its chunk, not the run — applied to the
    transport instead of the payload. Before this, a rejection cost one chunk of
    thirty-seven and a transient 500 cost everything after it, which is the more
    expensive failure treated as the less recoverable one.
    """
    attempts = {"n": 0}
    payload = {"obligations": []}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(500, text="upstream fell over")
        return httpx.Response(200, json={"response": json.dumps(payload)})

    extractor = build_extractor(
        Settings(_env_file=None, extractor_adapter="local")
    ).__class__(
        base_url="http://model", model="test-model",
        transport=httpx.MockTransport(flaky), backoff_seconds=0,
    )

    assert extractor.extract(PASSAGE, section_path=["3.2"]) == []
    assert attempts["n"] == 2, "the call was not retried"


def test_a_server_that_stays_broken_still_fails():
    """Retrying must not turn a wholly unavailable model into a silent success.
    The run has to end, and say what ended it."""
    attempts = {"n": 0}

    def always_500(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500, text="still down")

    extractor = build_extractor(
        Settings(_env_file=None, extractor_adapter="local")
    ).__class__(
        base_url="http://model", model="test-model",
        transport=httpx.MockTransport(always_500), backoff_seconds=0,
    )

    with pytest.raises(httpx.HTTPStatusError):
        extractor.extract(PASSAGE, section_path=["3.2"])
    assert attempts["n"] > 1, "it gave up without retrying"


def test_a_schema_rejection_is_not_retried():
    """A model that returned invalid output will return it again — retrying is
    pure cost, and ADR-023 already says this costs its chunk and continues."""
    attempts = {"n": 0}

    def bad_schema(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(
            200,
            json={"response": json.dumps({"obligations": [{"statement": "x"}]})},
        )

    extractor = build_extractor(
        Settings(_env_file=None, extractor_adapter="local")
    ).__class__(
        base_url="http://model", model="test-model",
        transport=httpx.MockTransport(bad_schema),
    )

    with pytest.raises(ValueError):
        extractor.extract(PASSAGE, section_path=["3.2"])
    assert attempts["n"] == 1


# --- ADR-030: an item costs itself, not its chunk -----------------------------

VALID = {
    "statement": "The Director shall notify the Comptroller.",
    "modality": "SHALL",
    "actor": "The Director",
    "deadline": None,
    "conditions": None,
    "confidence": 0.9,
}
# `modality: null` — the exact failure that cost 8 chunks in 37 on 2026-08-26,
# on sentences that state scope and name no duty.
INVALID = {**VALID, "statement": "This issuance applies to the OSD.", "modality": None}

# The passage VALID and INVALID were both read from. A statement is a quotation
# and that is now checked, so a stub adapter test has to hand the adapter a
# passage its fixtures actually occur in — `"..."` no longer stands in for one.
PASSAGE = "1.1.  SCOPE.\nThis issuance applies to the OSD.\nThe Director shall notify the Comptroller.\n"


def _local(payload, **kwargs):
    return LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"response": json.dumps(payload)})
        ),
        **kwargs,
    )


def test_one_unparseable_item_no_longer_costs_its_whole_chunk():
    """ADR-030. ADR-023's formula was "the extractor stays strict, the batch
    tolerates", applied to the run tolerating a bad chunk. A chunk is a batch too,
    and losing every obligation in it to one unlabelled sentence is a cost wholly
    out of proportion to the error."""
    extractor = _local({"obligations": [VALID, INVALID, {**VALID, "confidence": 0.5}]})

    found = extractor.extract(PASSAGE, section_path=["1.1"])

    assert len(found) == 2
    assert all(o.modality == "SHALL" for o in found)


def test_a_dropped_item_is_reported_rather_than_vanishing():
    """The condition ADR-030 attaches to the whole decision. Dropping quietly is
    the shape ADR-023's loud-failure argument warns about, and the count is the
    only thing keeping it honest — an implementation that drops without reporting
    has implemented something the ADR did not decide."""
    dropped = []
    extractor = _local({"obligations": [VALID, INVALID]})

    extractor.extract(PASSAGE, section_path=["1.1"], on_drop=dropped.append)

    assert len(dropped) == 1
    assert "modality" in dropped[0]


def test_a_chunk_where_nothing_validates_is_still_rejected():
    """Tolerating a bad item must not turn a wholly broken model into a green
    run. ADR-030 keeps this explicitly."""
    extractor = _local({"obligations": [INVALID, INVALID]})

    with pytest.raises(ValueError):
        extractor.extract(PASSAGE, section_path=["1.1"])


def test_an_empty_answer_is_still_not_a_rejection():
    """A passage stating no duty is the common case and always was."""
    extractor = _local({"obligations": []})

    assert extractor.extract(PASSAGE, section_path=["1.1"]) == []


def test_every_adapter_accepts_the_drop_reporter():
    """The port changed, so the adapters that never drop anything still have to
    honour the signature — otherwise the caller has to know which is which."""
    from policy_grapher.extraction.null import NullExtractor

    assert NullExtractor().extract("...", section_path=["1"], on_drop=print) == []


def test_an_assigned_item_from_the_wrong_section_costs_itself_and_not_its_chunk():
    """ADR-030 governs ADR-033's refusals.

    A model that returns one positional duty from a section that does not assign
    responsibilities has not returned a broken answer — it has returned one item
    this project refuses. The others survive, and the refusal is reported through
    `on_drop`, because a silent drop is the shape ADR-030 exists to prevent.
    """
    payload = {
        "obligations": [
            {
                "statement": "The Director shall notify the Comptroller.",
                "modality": "SHALL",
                "actor": "The Director",
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            },
            {
                "statement": "Monitors and evaluates the program.",
                "modality": "ASSIGNED",
                "actor": "DoD CIO",
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            },
        ]
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": json.dumps(payload)})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    dropped = []
    result = extractor.extract(
        "The Director shall notify the Comptroller.\nMonitors and evaluates the program.",
        section_path=["ENCLOSURE 3"],
        section_title="PROCEDURES",
        on_drop=dropped.append,
    )

    assert [o.modality for o in result] == ["SHALL"]
    assert len(dropped) == 1
    assert "responsibilities" in dropped[0]


def test_the_same_assigned_item_survives_in_a_responsibilities_section():
    """The other side of the guard: it refuses by section, not by modality."""
    payload = {
        "obligations": [
            {
                "statement": "Monitors and evaluates the program.",
                "modality": "ASSIGNED",
                "actor": "DoD CIO",
                "deadline": None,
                "conditions": None,
                "confidence": 0.9,
            }
        ]
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": json.dumps(payload)})
    )
    extractor = LocalExtractor(
        base_url="http://model", model="test-model", transport=transport
    )

    dropped = []
    result = extractor.extract(
        "1.  DoD CIO.  The DoD CIO:\na.  Monitors and evaluates the program.",
        section_path=["ENCLOSURE 2"],
        section_title="RESPONSIBILITIES",
        on_drop=dropped.append,
    )

    assert [o.modality for o in result] == ["ASSIGNED"]
    assert dropped == []


def test_the_prompt_version_moved_with_the_prompt():
    """PROMPT_VERSION participates in the cache key. An in-place prompt edit
    leaves the cache serving answers produced by a prompt that no longer exists,
    which is invisible and very hard to debug."""
    assert PROMPT_VERSION == 4


def test_the_prompt_still_refuses_headings_and_scope():
    """The two omissions that must survive this change.

    Removing the bare-task-list rule is the point of PROMPT_VERSION 3. Removing
    either of these is how "Be Responsive." comes back.
    """
    assert "Manage Efficiently" in EXTRACTION_PROMPT
    assert "This issuance applies to" in EXTRACTION_PROMPT


def test_the_prompt_teaches_the_positional_form_and_keeps_the_statement_verbatim():
    """ADR-033, and the identity constraint that shapes how it is taught.

    obligation_id hashes the normalised statement, so a statement the model
    *composes* — splicing the office from the heading into the sentence — varies
    with whatever wording it chooses and silently detaches the reviews recorded
    against that clause. The office belongs in `actor`.
    """
    assert "ASSIGNED" in EXTRACTION_PROMPT
    assert "word for word" in EXTRACTION_PROMPT


# --- bounding how much a model may generate ------------------------------------


def test_the_adapter_bounds_how_much_the_model_may_generate():
    """A timeout bounds waiting; it does not bound generating.

    Measured 2026-08-29: one gold fixture drove llama3.1:8b into a generation
    that produced no response for 3000 seconds — at 5.4 tokens/sec, roughly
    16,000 tokens and still going. `LocalExtractor` had a 600s timeout and three
    retries, so a single runaway chunk cost half an hour inside a rebuild that
    already runs for hours, and neither instrument could stop it.
    """
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps({"obligations": []})})

    extractor = LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(handler),
        max_output_tokens=1234,
    )
    extractor.extract(PASSAGE, section_path=["1.1"])

    assert seen["options"]["num_predict"] == 1234


def test_a_truncated_answer_is_rejected_and_says_the_cap_was_hit():
    """Truncation makes the JSON invalid, so the chunk is rejected either way.
    What matters is the reason: "model output was not JSON" sends a reader
    looking for a broken model, when the model was working and was cut off.
    """
    truncated = '{"obligations": [{"statement": "The Director shall act.", "moda'
    extractor = LocalExtractor(
        base_url="http://model",
        model="test-model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"response": truncated, "done_reason": "length"}
            )
        ),
    )

    with pytest.raises(ValueError) as excinfo:
        extractor.extract(PASSAGE, section_path=["1.1"])

    assert "num_predict" in str(excinfo.value)


def test_the_output_cap_leaves_room_for_the_longest_real_answer():
    """The default is set from measurement, not from a round number.

    Every gold fixture's legitimate answer was measured on 2026-08-29: the
    largest is 554 output tokens, paragraph 2.6's six obligations — one of the
    two sections sprint 11 exists to recover. A cap of 1024 would have truncated
    it, which is why the number was measured rather than picked.
    """
    from policy_grapher.config import Settings

    assert Settings(_env_file=None).extractor_max_output_tokens >= 554 * 2
