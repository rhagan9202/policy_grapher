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

    cache_variant: str
    """Anything beyond `adapter_id` that varies this adapter's answer.

    Empty when nothing does. Mandatory rather than optional for the same reason
    `on_drop` is: a caller that has to ask which adapter it is holding has lost
    the point of the port.
    """

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        """Obligations the passage states.

        `section_title` is the title of the part this chunk sits in, when the
        document wrote one. ADR-033 permits `ASSIGNED` only inside a section
        whose title names responsibilities, and the schema cannot check that —
        it validates an item without knowing where the item came from. Optional,
        and a `None` title simply never permits `ASSIGNED`, which is the correct
        conservative failure for a format whose titles we cannot read.

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
            max_output_tokens=settings.extractor_max_output_tokens,
            decoding=settings.extractor_decoding,
        )
    raise ValueError(f"unknown extractor adapter: {settings.extractor_adapter!r}")
