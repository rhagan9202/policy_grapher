"""Obligation extraction, behind a provider-agnostic port."""

from typing import TYPE_CHECKING, Protocol

from policy_grapher.extraction.schema import ExtractedObligation

if TYPE_CHECKING:
    from policy_grapher.config import Settings


class ObligationExtractor(Protocol):
    """The contract every adapter meets.

    `adapter_id` participates in the cache key, so it must change whenever the
    thing behind it changes — model, quantisation, or provider.
    """

    adapter_id: str

    def extract(
        self, chunk_text: str, *, section_path: list[str]
    ) -> list[ExtractedObligation]: ...


def build_extractor(settings: Settings) -> ObligationExtractor:
    """Resolve the configured adapter. Unknown names fail at startup, not mid-ingest."""
    from policy_grapher.extraction.local import LocalExtractor
    from policy_grapher.extraction.null import NullExtractor

    if settings.extractor_adapter == "null":
        return NullExtractor()
    if settings.extractor_adapter == "local":
        return LocalExtractor(
            base_url=settings.extractor_base_url, model=settings.extractor_model
        )
    raise ValueError(f"unknown extractor adapter: {settings.extractor_adapter!r}")
