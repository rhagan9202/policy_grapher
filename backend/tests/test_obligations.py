import json

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.cache import (
    CachedExtractor,
    GraphCacheStore,
    cache_key,
)
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.obligations import (
    UnknownAnchorError,
    drop_obligations,
    write_obligations,
)

KEY = {
    "chunk_text": "The Director shall notify the Comptroller.",
    "section_path": ["3.2"],
    "adapter_id": "local:llama3.1:8b",
    "prompt_version": 1,
}


# The same statement written twice with different modalities is the point of the
# rewrite test, and the schema now requires a statement to contain the modality it
# is labelled with — so this sentence carries both words.
BOTH_WORDS = "The Director shall notify the Comptroller and should log the call."


def _obligation(
    statement: str = "The Director shall notify the Comptroller.",
    modality: Modality = Modality.SHALL,
) -> ExtractedObligation:
    return ExtractedObligation(
        statement=statement,
        modality=modality,
        actor="The Director",
        deadline=None,
        conditions=None,
        confidence=0.8,
    )


class _RecordingExtractor:
    """Counts how many times the model would actually have been called."""

    adapter_id = "recording"

    def __init__(self, result: list[ExtractedObligation]) -> None:
        self.calls = 0
        self._result = result

    def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
        self.calls += 1
        return list(self._result)


class _DictStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def put(self, key: str, payload: str) -> None:
        self.data[key] = payload


# --- the cache key -----------------------------------------------------------


def test_the_cache_key_is_stable_for_identical_input():
    assert cache_key(**KEY) == cache_key(**KEY)


def test_the_cache_key_changes_when_the_adapter_changes():
    """Two models must never share a cached answer."""
    assert cache_key(**KEY) != cache_key(**{**KEY, "adapter_id": "local:other"})


def test_the_cache_key_changes_when_the_prompt_version_changes():
    """A prompt change is a version bump, and it must miss."""
    assert cache_key(**KEY) != cache_key(**{**KEY, "prompt_version": 2})


def test_the_cache_key_changes_when_the_chunk_text_changes():
    """Keyed on content, not on chunk_id: a re-chunk that reuses an id over
    different text must miss, or the cache answers from text that is gone."""
    assert cache_key(**KEY) != cache_key(
        **{**KEY, "chunk_text": "The Director may notify the Comptroller."}
    )


def test_the_cache_key_changes_when_the_section_changes():
    """section_path is rendered into the prompt, so it varies the answer."""
    assert cache_key(**KEY) != cache_key(**{**KEY, "section_path": ["4.1"]})


# --- the cache ---------------------------------------------------------------


def test_the_cache_calls_the_model_once_for_two_identical_requests():
    inner = _RecordingExtractor([_obligation()])
    cached = CachedExtractor(inner, _DictStore())

    first = cached.extract(KEY["chunk_text"], section_path=["3.2"])
    second = cached.extract(KEY["chunk_text"], section_path=["3.2"])

    assert inner.calls == 1
    assert first == second


def test_a_cache_hit_returns_validated_objects_not_raw_json():
    inner = _RecordingExtractor([_obligation()])
    cached = CachedExtractor(inner, _DictStore())
    cached.extract(KEY["chunk_text"], section_path=["3.2"])

    hit = cached.extract(KEY["chunk_text"], section_path=["3.2"])
    assert all(isinstance(o, ExtractedObligation) for o in hit)
    assert hit[0].modality is Modality.SHALL


def test_an_empty_result_is_cached_too():
    """Most chunks carry no obligation. Treating [] as a miss would re-run the
    model over the whole document on every rebuild, for nothing."""
    inner = _RecordingExtractor([])
    cached = CachedExtractor(inner, _DictStore())

    cached.extract("Table of contents.", section_path=["1"])
    cached.extract("Table of contents.", section_path=["1"])

    assert inner.calls == 1


def test_the_cache_misses_when_the_prompt_version_changes():
    store = _DictStore()
    inner = _RecordingExtractor([_obligation()])

    CachedExtractor(inner, store, prompt_version=1).extract("t", section_path=["1"])
    CachedExtractor(inner, store, prompt_version=2).extract("t", section_path=["1"])

    assert inner.calls == 2


def test_the_cache_reports_the_adapter_it_wraps():
    """Wrapping must be invisible to anything that keys off the adapter id."""
    assert CachedExtractor(_RecordingExtractor([]), _DictStore()).adapter_id == "recording"


# --- obligations in the graph ------------------------------------------------


def _seed_chunk(driver, database):
    driver.execute_query(
        "CREATE (d:Document {slug: 'd', name: 'D'})-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: 'v', checksum: 'x', source_uri: 'file:///d.pdf'})",
        database_=database,
    )
    chunks = chunk_pages(
        ["3.2. DUTIES.\nThe Director shall notify the Comptroller.\n"], version_id="v"
    )
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id="v", chunks=chunks)
    return chunks[-1]


@pytest.mark.integration
def test_an_obligation_hangs_off_its_version_and_anchors_to_its_chunk(
    clean_graph, database
):
    chunk = _seed_chunk(clean_graph, database)

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation()],
        )

    assert written == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v'})-[:MANDATES]->(o:Obligation)"
        "-[:ANCHORED_IN]->(c:Chunk) "
        "RETURN o.obligation_id AS id, o.modality AS modality, "
        "o.section_path AS path, o.confidence AS confidence, c.chunk_id AS chunk",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["modality"] == "SHALL"
    assert records[0]["path"] == ["3.2"]
    assert records[0]["chunk"] == chunk.chunk_id
    assert records[0]["id"] == obligation_id(
        "v", chunk.section_path, "The Director shall notify the Comptroller."
    )


@pytest.mark.integration
def test_confidence_is_recorded_rather_than_used_to_filter(clean_graph, database):
    """A low-confidence extraction still lands. Phase 4's review queue decides
    what a human sees; an extractor that hid its own doubt would hide its
    failures with it."""
    chunk = _seed_chunk(clean_graph, database)
    unsure = _obligation().model_copy(update={"confidence": 0.01})

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[unsure],
        )

    assert written == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN o.confidence AS confidence", database_=database
    )
    assert records[0]["confidence"] == pytest.approx(0.01)


@pytest.mark.integration
def test_writing_the_same_obligations_twice_creates_nothing_new(clean_graph, database):
    """Deterministic ids make re-extraction idempotent."""
    chunk = _seed_chunk(clean_graph, database)

    with clean_graph.session(database=database) as session:
        for _ in range(2):
            session.execute_write(
                write_obligations,
                version_id="v",
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[_obligation()],
            )

    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN count(o) AS total", database_=database
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_a_changed_statement_is_a_different_obligation(clean_graph, database):
    """Phase 5 diffs editions by identity, so a reworded duty must not silently
    overwrite the old one — it has to appear as a new node beside it."""
    chunk = _seed_chunk(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation()],
        )
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation("The Director shall notify the Secretary.")],
        )

    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN count(o) AS total", database_=database
    )
    assert records[0]["total"] == 2


@pytest.mark.integration
def test_rewriting_an_obligation_is_authoritative_about_its_fields(
    clean_graph, database
):
    """Identity ignores case and whitespace, so the same id can be reached with a
    different modality. The store must answer with the current reading."""
    chunk = _seed_chunk(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation(statement=BOTH_WORDS, modality=Modality.SHOULD)],
        )
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation(statement=BOTH_WORDS, modality=Modality.SHALL)],
        )

    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN o.modality AS modality", database_=database
    )
    assert [r["modality"] for r in records] == ["SHALL"]


@pytest.mark.integration
def test_dropping_obligations_leaves_chunks_and_versions_standing(
    clean_graph, database
):
    """The derived layer is droppable; what it was derived from is not touched."""
    chunk = _seed_chunk(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[_obligation()],
        )
        dropped = session.execute_write(drop_obligations, version_id="v")

    assert dropped == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) WITH count(o) AS obligations "
        "MATCH (c:Chunk) WITH obligations, count(c) AS chunks "
        "MATCH (v:DocumentVersion) RETURN obligations, chunks, count(v) AS versions",
        database_=database,
    )
    assert records[0]["obligations"] == 0
    assert records[0]["chunks"] > 0
    assert records[0]["versions"] == 1


@pytest.mark.integration
def test_writing_against_an_unknown_anchor_fails_loudly(clean_graph, database):
    """A silent no-match would report success having written nothing."""
    _seed_chunk(clean_graph, database)

    with (
        clean_graph.session(database=database) as session,
        pytest.raises(UnknownAnchorError),
    ):
        session.execute_write(
            write_obligations,
            version_id="v",
            chunk_id="not-a-chunk",
            section_path=["3.2"],
            obligations=[_obligation()],
        )


@pytest.mark.integration
def test_the_graph_backed_cache_survives_a_new_extractor(clean_graph, database):
    """Backed by the graph rather than a process-local dict, so a rebuild after a
    restart is still cheap."""
    store = GraphCacheStore(clean_graph, database)
    inner = _RecordingExtractor([_obligation()])

    CachedExtractor(inner, store).extract(KEY["chunk_text"], section_path=["3.2"])
    result = CachedExtractor(inner, store).extract(
        KEY["chunk_text"], section_path=["3.2"]
    )

    assert inner.calls == 1
    assert result[0].statement == _obligation().statement


def test_a_cache_entry_that_no_longer_validates_costs_only_that_item():
    """The cache outlives the rules it was filled under.

    Measured 2026-08-27: three entries in the live graph held statements written
    before the schema began requiring a statement to contain its modality — "Be
    Responsive." labelled SHALL. A hit re-validates, so those chunks would have
    raised on replay, and `rebuild_derived` catches that as a *chunk* rejection —
    losing the valid obligations cached alongside them.

    That is precisely the blast radius ADR-030 moved, reappearing at the cache
    boundary because the rule was applied where items are extracted and not where
    they are replayed. A cached item that no longer validates is the same event as
    a fresh one that does not: it costs itself.
    """
    store = _DictStore()
    key = cache_key(**{**KEY, "adapter_id": "recording", "prompt_version": 1})
    # One statement that still validates and one written under the older rules.
    store.put(
        key,
        json.dumps(
            [
                {
                    "statement": "The Director shall notify the Comptroller.",
                    "modality": "SHALL",
                    "actor": None, "deadline": None, "conditions": None,
                    "confidence": 0.9,
                },
                {
                    "statement": "Be Responsive.",
                    "modality": "SHALL",
                    "actor": None, "deadline": None, "conditions": None,
                    "confidence": 0.9,
                },
            ]
        ),
    )
    dropped: list[str] = []
    cached = CachedExtractor(_RecordingExtractor([]), store, prompt_version=1)

    found = cached.extract(KEY["chunk_text"], section_path=["3.2"], on_drop=dropped.append)

    assert [o.statement for o in found] == ["The Director shall notify the Comptroller."]
    assert len(dropped) == 1


def test_a_cache_entry_where_nothing_validates_is_still_a_rejection():
    """ADR-030's other half, and it has to hold on replay too: a chunk that
    produces no valid obligation is a rejected chunk, not an empty answer."""
    store = _DictStore()
    key = cache_key(**{**KEY, "adapter_id": "recording", "prompt_version": 1})
    store.put(
        key,
        json.dumps(
            [
                {
                    "statement": "Be Responsive.",
                    "modality": "SHALL",
                    "actor": None, "deadline": None, "conditions": None,
                    "confidence": 0.9,
                }
            ]
        ),
    )
    cached = CachedExtractor(_RecordingExtractor([]), store, prompt_version=1)

    with pytest.raises(ValueError):
        cached.extract(KEY["chunk_text"], section_path=["3.2"])


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
