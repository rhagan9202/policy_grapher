"""Obligation extraction, behind a provider-agnostic port."""

from collections.abc import Callable
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
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        """Obligations the passage states.

        `on_drop`, when given, is called once per item the adapter discarded for
        failing validation, with the reason. ADR-030 makes reporting them part of
        the decision to drop them at all: dropping quietly is the shape ADR-023's
        loud-failure argument warns about, and the count is the only thing left
        keeping it honest. An adapter that cannot produce an invalid item never
        calls it, and still has to accept it — otherwise the caller has to know
        which adapter it is holding.
        """
        ...


def build_extractor(settings: Settings) -> ObligationExtractor:
    """Resolve the configured adapter. Unknown names fail at startup, not mid-ingest."""
    from policy_grapher.extraction.local import LocalExtractor
    from policy_grapher.extraction.null import NullExtractor

    if settings.extractor_adapter == "null":
        return NullExtractor()
    if settings.extractor_adapter == "local":
        return LocalExtractor(
            base_url=settings.extractor_base_url,
            model=settings.extractor_model,
            timeout_seconds=settings.extractor_timeout_seconds,
        )
    raise ValueError(f"unknown extractor adapter: {settings.extractor_adapter!r}")
