"""Obligation extraction, behind a provider-agnostic port."""

from typing import Protocol

from policy_grapher.extraction.schema import ExtractedObligation


class ObligationExtractor(Protocol):
    """The contract every adapter meets.

    `adapter_id` participates in the cache key, so it must change whenever the
    thing behind it changes — model, quantisation, or provider.
    """

    adapter_id: str

    def extract(
        self, chunk_text: str, *, section_path: list[str]
    ) -> list[ExtractedObligation]: ...
