

def test_the_cache_key_ignores_the_section_title():
    """A chunk's title is a function of its path, which the key already holds.

    Including it would change every existing key and discard the cached
    extractions the graph is holding — 145 of them on 2026-08-27 — to
    distinguish nothing.
    """
    from policy_grapher.extraction.cache import cache_key

    common = {
        "section_path": ["SECTION 2", "2.2"],
        "adapter_id": "local",
        "prompt_version": 3,
    }
    assert cache_key("a passage", **common) == cache_key("a passage", **common)
    assert cache_key("a passage", **common) != cache_key("another", **common)


def test_the_cache_forwards_the_section_title_to_the_adapter_behind_it():
    """ADR-033's guard runs inside the adapter, so a cache miss must carry the
    title through or the guard sees None and refuses every positional duty."""
    from policy_grapher.extraction.cache import CachedExtractor

    seen = {}

    class Recording:
        adapter_id = "recording"

        def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
            seen["section_title"] = section_title
            return []

    class Store:
        def get(self, key):
            return None

        def put(self, key, value):
            pass

    CachedExtractor(Recording(), Store(), prompt_version=3).extract(
        "a passage", section_path=["SECTION 2"], section_title="RESPONSIBILITIES"
    )

    assert seen["section_title"] == "RESPONSIBILITIES"
