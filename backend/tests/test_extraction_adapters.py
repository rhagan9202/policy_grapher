import json

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
        LocalExtractor(base_url="http://m", model="qwen3:8b").adapter_id
        == "local:qwen3:8b"
    )


def test_an_unknown_adapter_name_fails_loudly():
    """Better at startup than mid-ingest, halfway through a document."""
    with pytest.raises(ValueError, match="unknown extractor adapter"):
        build_extractor(Settings(_env_file=None, extractor_adapter="gpt-9"))
