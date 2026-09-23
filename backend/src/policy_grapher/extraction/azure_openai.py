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


def _error_code(response: httpx.Response) -> str | None:
    try:
        return (response.json().get("error") or {}).get("code")
    except (ValueError, AttributeError):
        return None


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
        try:
            answer = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("Azure OpenAI returned a body that was not JSON") from exc

        served = answer.get("model")
        if served != self._model:
            raise ValueError(
                f"Azure served {served!r}, but AZURE_OPENAI_MODEL is {self._model!r}. The "
                f"deployment now serves a different model than the one this adapter's id — "
                f"and so the extraction cache — names; update AZURE_OPENAI_MODEL."
            )

        choices = answer.get("choices") or []
        if not choices:
            raise ValueError("Azure OpenAI returned a response with no choices")
        choice = choices[0]
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
