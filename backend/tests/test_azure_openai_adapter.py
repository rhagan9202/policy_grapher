"""The Azure OpenAI extraction adapter (spec: docs/superpowers/specs/
2026-09-23-azure-openai-extraction-adapter-design.md). Every test is offline:
the live key cannot be used on this machine, and a test that needed it would
have strayed into the manual check the spec's §7 describes."""

import json

import httpx
import pytest
from pydantic import SecretStr

from policy_grapher.config import Settings
from policy_grapher.extraction import azure_openai, build_extractor
from policy_grapher.extraction.azure_openai import (
    STRICT_SCHEMA,
    UNSUPPORTED_KEYWORDS,
    AzureOpenAIExtractor,
    ServedModelMismatch,
)
from policy_grapher.extraction.prompt import EXTRACTION_PROMPT
from policy_grapher.extraction.schema import ExtractionPayload

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


@pytest.mark.parametrize(
    "endpoint,named",
    [
        ("https://x.openai.azure.us/openai", "path"),
        ("https://x.openai.azure.us/openai/", "path"),
        ("https://x.openai.azure.us?q=1", "query"),
        ("https://x.openai.azure.us/?q=1", "query"),
        ("https://x.openai.azure.us#f", "fragment"),
        ("https://user:pw@x.openai.azure.us", "user"),
        ("https://user@x.openai.azure.us", "user"),
    ],
)
def test_an_endpoint_with_more_than_a_host_is_refused_by_what_to_remove(endpoint, named):
    """The adapter appends `/openai/deployments/...` itself, so a path doubles it,
    and a query, fragment or userinfo has no place in a base URL."""
    with pytest.raises(ValueError, match=named):
        _adapter(endpoint=endpoint)


def test_a_refused_endpoint_does_not_echo_its_password():
    with pytest.raises(ValueError) as caught:
        _adapter(endpoint="https://user:s3cr3t-pw@x.openai.azure.us")
    assert "s3cr3t-pw" not in str(caught.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://policy-grapher.openai.azure.us/",
        "https://policy-grapher.openai.azure.us",
        "https://policy-grapher.openai.azure.us:443",
    ],
)
def test_an_azure_government_host_is_accepted(endpoint):
    adapter, seen = _captured(endpoint=endpoint)
    adapter.extract(PASSAGE, section_path=["1"])
    assert seen[0].url.path == "/openai/deployments/extract/chat/completions"


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


def test_the_strict_schema_does_not_send_the_developer_docstring():
    """ExtractionPayload's docstring is a note to maintainers about local.py and
    parsing; sent on every billed call it would be prompt text nobody reviewed."""
    assert "description" not in STRICT_SCHEMA
    assert ExtractionPayload.model_json_schema().get("description"), (
        "the source schema has no top-level description; this test guards nothing"
    )


def test_the_strict_schema_keeps_the_modality_description():
    assert STRICT_SCHEMA["$defs"]["Modality"].get("description")


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
        (lambda request: httpx.Response(200, json=[_completion("{}")]), "not an object"),
        (
            lambda request: httpx.Response(200, json={"model": MODEL, "choices": ["x"]}),
            "choice",
        ),
        (
            lambda request: httpx.Response(
                200, json={"model": MODEL, "choices": [{"message": "x"}]}
            ),
            "message",
        ),
        (
            lambda request: httpx.Response(
                200,
                json={"model": MODEL, "choices": [{"message": {"content": {"obligations": []}}}]},
            ),
            "content",
        ),
        (_answering([GOOD]), "not an object"),
        (_answering({"obligations": None}), "obligations"),
        (_answering({"obligations": {"x": GOOD}}), "obligations"),
    ],
    ids=[
        "length",
        "filter-finish",
        "refusal",
        "null-content",
        "not-json",
        "filter-400",
        "no-choices-missing",
        "no-choices-empty",
        "not-json-200",
        "body-is-a-list",
        "choice-not-object",
        "message-not-object",
        "content-not-string",
        "payload-is-a-list",
        "obligations-null",
        "obligations-object",
    ],
)
def test_a_failed_answer_costs_its_chunk_and_names_why(handler, cause):
    """ValueError is what rebuild.py:334 catches: the chunk is rejected, the run goes on."""
    with pytest.raises(ValueError, match=cause):
        _adapter(handler).extract(PASSAGE, section_path=["1"])


def test_a_retargeted_deployment_ends_the_run_rather_than_costing_every_chunk():
    """Spec §3.4: a deployment answering with a different model answers every
    chunk that way. As a ValueError it would bill and discard all 204 chunks;
    it is a configuration error and stops on the first."""
    handler = _answering({"obligations": [GOOD]}, model="gpt-4o-2024-08-06")
    with pytest.raises(ServedModelMismatch, match="gpt-4o-2024-08-06") as caught:
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    assert not isinstance(caught.value, ValueError)
    assert "AZURE_OPENAI_MODEL" in str(caught.value)


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


@pytest.mark.parametrize(
    "status,error,shown",
    [
        (
            400,
            {
                "code": "unsupported_parameter",
                "message": "Unsupported parameter: 'temperature' is not supported with this model.",
            },
            ["400", "unsupported_parameter", "temperature"],
        ),
        (
            404,
            {
                "code": "DeploymentNotFound",
                "message": "The API deployment for this resource does not exist.",
            },
            ["404", "DeploymentNotFound", "does not exist"],
        ),
    ],
    ids=["effort-mismatch", "no-deployment"],
)
def test_a_refused_request_ends_the_run_in_azures_own_words(status, error, shown):
    """The manual live check has to tell an effort/model mismatch, a refused
    schema keyword and a missing deployment apart; httpx's own text names none."""

    def handler(request):
        return httpx.Response(status, json={"error": error})

    with pytest.raises(httpx.HTTPStatusError) as caught:
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    for word in shown:
        assert word in str(caught.value)
    assert caught.value.response.status_code == status


def test_a_long_azure_message_is_cut_short():
    def handler(request):
        return httpx.Response(400, json={"error": {"code": "x", "message": "m" * 5000}})

    with pytest.raises(httpx.HTTPStatusError) as caught:
        _adapter(handler).extract(PASSAGE, section_path=["1"])
    assert "m" * 300 in str(caught.value)
    assert "m" * 301 not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, content=b"<html>Bad Gateway</html>"),
        httpx.Response(400, json={"detail": "no error object"}),
        httpx.Response(400, json=["a", "list"]),
        httpx.Response(400, json={"error": "a string"}),
    ],
    ids=["html", "no-error-key", "list-body", "error-not-object"],
)
def test_a_refusal_without_azures_error_object_still_ends_the_run(response):
    status = response.status_code

    def handler(request):
        return response

    with pytest.raises(httpx.HTTPStatusError, match=str(status)):
        _adapter(handler).extract(PASSAGE, section_path=["1"])


def test_no_failure_message_carries_the_key_or_the_passage():
    for handler in (
        _answering(None, refusal="no"),
        _answering({"obligations": []}, model="other"),
        lambda request: httpx.Response(401, json={}),
        lambda request: httpx.Response(
            400, json={"error": {"code": "invalid_request_error", "message": "bad request"}}
        ),
    ):
        with pytest.raises(Exception) as caught:
            _adapter(handler).extract(PASSAGE, section_path=["1"])
        assert KEY not in str(caught.value)
        assert "shall notify the Comptroller" not in str(caught.value)


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


# --- wiring --------------------------------------------------------------------------


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "extractor_adapter": "azure",
        "azure_openai_endpoint": ENDPOINT,
        "azure_openai_api_key": KEY,
        "azure_openai_deployment": "extract",
        "azure_openai_api_version": "2025-04-01-preview",
        "azure_openai_model": MODEL,
    }
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
