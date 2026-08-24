"""The job a worker runs to build one edition's derived layer.

It takes primitives, not objects: RQ serialises a job's arguments through Redis,
so a driver or a Settings instance could not cross that boundary. The worker
resolves its own configuration and opens its own driver, and closes it again — a
worker process outlives any single job and would otherwise leak one per run.
"""

from neo4j import Driver
from rq import get_current_job

from policy_grapher.config import Settings, get_settings
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


# Enough to see the shape of a failure without letting a pathological run write an
# unbounded blob into Redis. A run rejecting more than this has a systemic problem,
# and the count still reports the true total.
REPORTED_REJECTIONS = 20


def _rejection_reporter():
    """Records why chunks were rejected, onto the same job meta progress uses.

    Meta rather than the return value because `counts` is `dict[str, int]`, and
    because meta is written during the run — so an operator watching a long
    rebuild sees the reasons as they happen rather than an hour later.
    """
    job = get_current_job()
    if job is None:
        return None

    def report(chunk_id: str, reason: str) -> None:
        rejections = job.meta.setdefault("rejections", [])
        if len(rejections) < REPORTED_REJECTIONS:
            rejections.append({"chunk_id": chunk_id, "reason": reason})
            job.save_meta()

    return report


def _record_adapters(settings: Settings) -> None:
    """Record which extractor and embedder actually ran, onto the job's meta.

    The worker resolves its own configuration, so the API cannot report this
    from its own settings and be sure it is true. It has to come from here.

    Without it a rebuild under `EXTRACTOR_ADAPTER=null` finishes cleanly having
    written every chunk and zero obligations, and the screen reports exactly
    that: a successful run that produced nothing, with no way to tell a
    deliberately disabled extractor from a broken one. That is the state
    ADR-019 forbids a screen from presenting — emptiness has to say why it is
    empty.
    """
    job = get_current_job()
    if job is None:
        return
    job.meta["extractor_adapter"] = settings.extractor_adapter
    job.meta["embedder_adapter"] = settings.embedder_adapter
    job.save_meta()


def _run(
    driver: Driver, database: str, settings: Settings, **kwargs
) -> dict[str, int]:
    # Cached on purpose (ADR-013): a second run over an unchanged edition calls
    # the model zero times, which is what makes re-extraction cheap enough to be
    # routine rather than an event.
    _record_adapters(settings)
    extractor = CachedExtractor(
        build_extractor(settings), GraphCacheStore(driver, database)
    )
    counts = rebuild_derived(
        driver,
        database,
        extractor=extractor,
        on_progress=_progress_reporter(),
        on_rejection=_rejection_reporter(),
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
