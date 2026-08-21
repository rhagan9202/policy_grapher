"""The job a worker runs to build one edition's derived layer.

It takes primitives, not objects: RQ serialises a job's arguments through Redis,
so a driver or a Settings instance could not cross that boundary. The worker
resolves its own configuration and opens its own driver, and closes it again — a
worker process outlives any single job and would otherwise leak one per run.
"""

from neo4j import Driver
from rq import get_current_job

from policy_grapher.config import get_settings
from policy_grapher.db import create_driver
from policy_grapher.embedding import build_embedder, embed_chunks
from policy_grapher.extraction import build_extractor
from policy_grapher.extraction.cache import CachedExtractor, GraphCacheStore
from policy_grapher.links.rebuild import rebuild_derived


def _progress_reporter():
    """Write progress where a poller can read it.

    `get_current_job` returns None when the function is called directly rather
    than through a queue, which the unit tests do — so this degrades to no
    reporting instead of requiring a queue to exist.
    """
    job = get_current_job()
    if job is None:
        return None

    def report(done: int, total: int) -> None:
        job.meta["chunks_done"] = done
        job.meta["chunks_total"] = total
        job.save_meta()

    return report


def _run(driver: Driver, database: str, settings, **kwargs) -> dict[str, int]:
    # Cached on purpose (ADR-013): a second run over an unchanged edition calls
    # the model zero times, which is what makes re-extraction cheap enough to be
    # routine rather than an event.
    extractor = CachedExtractor(
        build_extractor(settings), GraphCacheStore(driver, database)
    )
    counts = rebuild_derived(
        driver,
        database,
        extractor=extractor,
        on_progress=_progress_reporter(),
        **kwargs,
    )
    counts["embedded"] = embed_chunks(
        driver,
        database,
        version_id=kwargs["version_id"],
        embedder=build_embedder(settings),
    )
    return counts


def rebuild_edition(
    version_id: str,
    candidate_version_ids: list[str] | None = None,
    proposer: str = "lexical-v1",
) -> dict[str, int]:
    """Rebuild one edition's derived layer, then embed its chunks.

    Returns the counts `rebuild_derived` reports plus `embedded`. Raises
    `MissingSourceError` if the edition or its source file is gone — the route
    checks for that before enqueueing, so reaching it here means the file
    disappeared between the check and the run, or the worker cannot see it.
    """
    settings = get_settings()
    driver = create_driver(settings)
    try:
        return _run(
            driver,
            settings.neo4j_database,
            settings,
            version_id=version_id,
            candidate_version_ids=candidate_version_ids,
            proposer=proposer,
        )
    finally:
        driver.close()
