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

# Only the fallback for a caller that does not pass one; `build_extractor` always
# passes `Settings.extractor_timeout_seconds`. Kept generous for the same reason that
# setting is (STORY-058).
DEFAULT_TIMEOUT_SECONDS = 600.0


class LocalExtractor:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client = httpx.Client(transport=transport, timeout=timeout_seconds)

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
