"""The adapter that extracts nothing.

The default, so `uv run pytest` passes on a machine with no model server. A
suite that cannot run without infrastructure stops being run.
"""

from collections.abc import Callable

from policy_grapher.extraction.schema import ExtractedObligation


class NullExtractor:
    adapter_id = "null"

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        return []
