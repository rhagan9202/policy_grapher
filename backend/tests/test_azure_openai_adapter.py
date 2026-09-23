"""The Azure OpenAI extraction adapter (spec: docs/superpowers/specs/
2026-09-23-azure-openai-extraction-adapter-design.md). Every test is offline:
the live key cannot be used on this machine, and a test that needed it would
have strayed into the manual check the spec's §7 describes."""

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
    kwargs = {
        "endpoint": ENDPOINT,
        "api_key": SecretStr(KEY),
        "deployment": "extract",
        "api_version": "2025-04-01-preview",
        "model": MODEL,
        "backoff_seconds": 0,
        "sleep": lambda seconds: None,
    }
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
        for value in node.values():
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
