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
from policy_grapher.extraction.prompt import EXTRACTION_PROMPT

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
        (lambda request: httpx.Response(200, json={"model": MODEL}), "no choices"),
        (
            lambda request: httpx.Response(200, json={"model": MODEL, "choices": []}),
            "no choices",
        ),
        (lambda request: httpx.Response(200, content=b"<html>"), "not JSON"),
    ],
    ids=[
        "length",
        "filter-finish",
        "refusal",
        "null-content",
        "not-json",
        "model-drift",
        "filter-400",
        "no-choices-missing",
        "no-choices-empty",
        "not-json-200",
    ],
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

    def handler(request):
        return httpx.Response(401, json={"error": {"code": "401"}})

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
