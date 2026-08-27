"""Extraction results, keyed by what actually determined them.

Extraction is the expensive step, and a rebuild re-asks the same questions. The
cache makes rebuilds cheap and adapter comparisons like-for-like — but only if
the key covers everything that varies the answer. It covers three things:

- **the content**, not the chunk id. A chunk id is a hash of *where* a chunk
  sits (chunking._chunk_id), deliberately not of its text, so that a re-chunk
  preserves anchors. Keying on it would let an edited edition reuse an id over
  different words and be answered from text that no longer exists.
- **the section path**, because it is rendered into the prompt and so changes
  what the model was asked.
- **the adapter and the prompt version**, because both change the asker.

A prompt edit is a `PROMPT_VERSION` bump, never an in-place change: an in-place
edit leaves this cache serving results from a prompt that no longer exists.
"""

import hashlib
import json
from collections.abc import Callable
from typing import Protocol

from neo4j import Driver, RoutingControl
from pydantic import ValidationError

from policy_grapher.extraction.prompt import PROMPT_VERSION
from policy_grapher.extraction.schema import ExtractedObligation

READ_CACHE = "MATCH (e:ExtractionCache {key: $key}) RETURN e.payload_json AS payload"

WRITE_CACHE = """
MERGE (e:ExtractionCache {key: $key})
SET e.payload_json = $payload
"""


def cache_key(
    chunk_text: str,
    *,
    section_path: list[str],
    adapter_id: str,
    prompt_version: int,
) -> str:
    content = hashlib.sha256(
        f"{'/'.join(section_path)}\n{chunk_text}".encode()
    ).hexdigest()
    return f"{adapter_id}|{prompt_version}|{content}"


class CacheStore(Protocol):
    """Somewhere to keep a payload under a key. A dict satisfies this; the
    shipped implementation is the graph, so a restart does not lose the work."""

    def get(self, key: str) -> str | None: ...

    def put(self, key: str, payload: str) -> None: ...


class GraphCacheStore:
    """The cache table, in Neo4j.

    Its own transactions on purpose: a cached result is not part of the graph's
    meaning, and a cache write must not be able to roll back an ingest.
    """

    def __init__(self, driver: Driver, database: str) -> None:
        self._driver = driver
        self._database = database

    def get(self, key: str) -> str | None:
        records, _, _ = self._driver.execute_query(
            READ_CACHE,
            {"key": key},
            database_=self._database,
            routing_=RoutingControl.READ,
        )
        return records[0]["payload"] if records else None

    def put(self, key: str, payload: str) -> None:
        self._driver.execute_query(
            WRITE_CACHE,
            {"key": key, "payload": payload},
            database_=self._database,
            routing_=RoutingControl.WRITE,
        )


class CachedExtractor:
    """Any extractor, memoised. Satisfies `ObligationExtractor` itself, so it
    wraps transparently and reports the adapter id of what it wraps — anything
    keying off the adapter must not see the wrapper instead."""

    def __init__(
        self,
        inner,
        store: CacheStore,
        prompt_version: int = PROMPT_VERSION,
    ) -> None:
        self._inner = inner
        self._store = store
        self._prompt_version = prompt_version

    @property
    def adapter_id(self) -> str:
        return self._inner.adapter_id

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        on_drop: Callable[[str], None] | None = None,
    ) -> list[ExtractedObligation]:
        key = cache_key(
            chunk_text,
            section_path=section_path,
            adapter_id=self._inner.adapter_id,
            prompt_version=self._prompt_version,
        )
        # `is not None`, not a truth test: an empty list is the common and
        # correct answer for most passages, and treating it as a miss would
        # re-run the model over the whole document on every rebuild.
        payload = self._store.get(key)
        if payload is not None:
            # ADR-030 applies on replay too, and it has to: the cache outlives the
            # rules it was filled under. Three entries in the live graph on
            # 2026-08-27 held statements written before the schema required a
            # statement to contain its modality, and re-validating them raised —
            # which `rebuild_derived` catches as a *chunk* rejection, losing the
            # valid obligations cached beside them. That is the blast radius
            # ADR-030 moved, reappearing because the rule was applied where items
            # are extracted and not where they are replayed.
            replayed: list[ExtractedObligation] = []
            stale = 0
            for item in json.loads(payload):
                try:
                    replayed.append(ExtractedObligation.model_validate(item))
                except ValidationError as exc:
                    stale += 1
                    if on_drop is not None:
                        on_drop(f"cached item no longer validates: {exc}")
            if stale and not replayed:
                raise ValueError(
                    f"every cached obligation for this chunk is now invalid "
                    f"({stale} of {stale})"
                )
            return replayed

        # Forwarded on a miss only. A hit replays items that already validated,
        # so there is nothing left to drop — and re-reporting the drops from the
        # run that populated the cache would double-count them.
        result = self._inner.extract(
            chunk_text, section_path=section_path, on_drop=on_drop
        )
        self._store.put(
            key, json.dumps([o.model_dump(mode="json") for o in result])
        )
        return result
