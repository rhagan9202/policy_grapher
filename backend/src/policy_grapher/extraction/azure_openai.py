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

from policy_grapher.extraction.schema import ExtractionPayload

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
