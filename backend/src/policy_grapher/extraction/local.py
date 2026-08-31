"""A local model served over HTTP (Ollama-compatible).

Constrained decoding via the server's JSON mode is requested where available,
but it is an optimisation: every response is validated against our own schema
regardless, because that is what keeps behaviour identical across adapters.
"""

import json
import time
from collections.abc import Callable

import httpx

from policy_grapher.extraction.prompt import EXTRACTION_PROMPT
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    ExtractionPayload,
    validate_extracted,
)

# Only the fallback for a caller that does not pass one; `build_extractor` always
# passes `Settings.extractor_timeout_seconds`. Kept generous for the same reason that
# setting is (STORY-058).
DEFAULT_TIMEOUT_SECONDS = 600.0

# Between retries of a transport failure. Short, because the failure this exists
# for was momentary — the server answered normally on the next call — and because
# `timeout_seconds` is already the bound on a model that has stopped responding
# rather than fallen over.
DEFAULT_BACKOFF_SECONDS = 2.0
# See `Settings.extractor_max_output_tokens` for how this number was measured.
DEFAULT_MAX_OUTPUT_TOKENS = 2048

# Generated once at import: it is a pure function of the models, and rebuilding
# it per call would put a schema walk inside a loop over every chunk.
_RESPONSE_SCHEMA = ExtractionPayload.model_json_schema()


class LocalExtractor:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        decoding: str = "schema",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)
        self._backoff_seconds = backoff_seconds
        self._max_output_tokens = max_output_tokens
        self._runtime_version: str | None = None
        if decoding not in ("schema", "json"):
            raise ValueError(f"unknown decoding mode: {decoding!r}")
        self._decoding = decoding

    @property
    def adapter_id(self) -> str:
        return f"local:{self._model}"

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

    # A 37-chunk rebuild died at chunk 24 on a single 500 from a model server that
    # was healthy again seconds later and had served twenty-three calls before it.
    # ADR-023 already settled the principle for a chunk whose *output* fails the
    # schema — one bad item costs its chunk, not the run — and the transport was
    # left outside it, so the cheaper failure was recoverable and the more
    # expensive one was not.
    #
    # Only transport-level failures are retried. A schema rejection is not: a model
    # that returned invalid output will return it again, so retrying is pure cost,
    # and ADR-023 says that case already costs its chunk and continues.
    RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
    ATTEMPTS = 3

    def _post_with_retries(
        self, chunk_text: str, section_path: list[str]
    ) -> httpx.Response:
        body = {
            "model": self._model,
            "prompt": EXTRACTION_PROMPT.format(
                section_path="/".join(section_path), chunk_text=chunk_text
            ),
            # A schema here is constrained decoding: the server masks any token
            # that would violate it, so an invalid modality or a missing field
            # cannot be emitted. The string "json" is the legacy mode and only
            # guarantees the output parses. Either way every item is still
            # validated by `validate_extracted` below — a hosted adapter may not
            # constrain at all, and behaviour has to match across adapters.
            "format": _RESPONSE_SCHEMA if self._decoding == "schema" else "json",
            "stream": False,
            # num_predict bounds generation itself. The timeout above bounds only
            # waiting, and a model that never stops will exhaust it three times
            # over — measured at 3000 seconds on one chunk before this existed.
            "options": {
                "temperature": 0,
                "num_predict": self._max_output_tokens,
            },
        }
        url = f"{self._base_url}/api/generate"

        for attempt in range(1, self.ATTEMPTS + 1):
            last = attempt == self.ATTEMPTS
            try:
                response = self._client.post(url, json=body)
            except httpx.TransportError:
                # A dropped connection mid-run is the same failure as a 500 and has
                # the same consequence; a rebuild is hours long and the socket has
                # every opportunity to die once.
                if last:
                    raise
            else:
                if response.status_code not in self.RETRYABLE_STATUS or last:
                    return response
            time.sleep(self._backoff_seconds)

        raise AssertionError("unreachable: the loop returns or raises on its last pass")

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        response = self._post_with_retries(chunk_text, section_path)
        response.raise_for_status()
        body = response.json()
        raw = body["response"]

        # Truncation makes the JSON invalid, so this chunk would be rejected
        # either way. The reason is what changes: "model output was not JSON"
        # sends a reader looking for a broken model, when the model was working
        # and was cut off.
        if body.get("done_reason") == "length":
            raise ValueError(
                f"the model hit its output cap (num_predict="
                f"{self._max_output_tokens}) and its answer was truncated. This "
                f"chunk is rejected rather than partly read; a passage whose real "
                f"answer needs more than the cap needs the cap raised, and one "
                f"that never stops needs the cap."
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model output was not JSON: {raw[:200]!r}") from exc

        # ADR-030. Each item is validated on its own, and one that fails costs
        # itself rather than everything that shared its chunk. Measured 2026-08-26:
        # eight chunks in thirty-seven were lost whole, every one of them to a
        # single `modality: null` on a sentence stating scope and naming no duty.
        #
        # The strictness is unchanged — `Modality` is still closed and an invalid
        # item is still not written. What changed is the blast radius.
        items = payload.get("obligations", [])
        found: list[ExtractedObligation] = []
        reasons: list[str] = []
        for item in items:
            try:
                found.append(
                    validate_extracted(
                        item,
                        section_title=section_title,
                        chunk_text=chunk_text,
                    )
                )
            # `ValueError`, not `ValidationError`: ADR-033's section guard is not
            # a field rule and raises plainly, and `ValidationError` subclasses
            # `ValueError`, so this catches both without the loop needing to know
            # which rule refused the item.
            except ValueError as exc:
                reason = f"model output did not match the obligation schema: {exc}"
                reasons.append(reason)
                if on_drop is not None:
                    on_drop(reason)

        # Nothing validated out of something the model did return: that is a
        # wholly broken answer, not a passage without duties, and ADR-030 keeps it
        # a rejected chunk. An empty `obligations` list is the ordinary case and
        # reaches here with no reasons, so it stays an empty answer.
        if reasons and not found:
            raise ValueError(reasons[0])

        return found
