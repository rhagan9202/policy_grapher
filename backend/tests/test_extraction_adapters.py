import json
from pathlib import Path

import httpx
import pytest

from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor
from policy_grapher.extraction.local import LocalExtractor
from policy_grapher.extraction.null import NullExtractor


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
