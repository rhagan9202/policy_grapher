"""What a rebuild did to one edition, recorded where it outlives the run.

STORY-082. An edition holding zero obligations has three causes needing
different actions — never built, built with the `null` extractor which writes
chunks and no obligations by design (ADR-028), or a run that died partway — and
until this module nothing durable told them apart.

Recorded in the graph, not in RQ. RQ is deliberately forgetful:
`rebuild_result_ttl_seconds` expires a run's result after a day so a queue does
not accumulate them, which means it can answer "how is this run going" and can
never answer "was this edition ever built". The graph is where durable facts
live, and `ExtractionCache` (ADR-013) already set that precedent.

The record is the *current or last* build, one per edition, overwritten by each
run. A log of every run that ever executed needs a retention decision this does
not take.
"""

import json
from datetime import UTC, datetime

from neo4j import ManagedTransaction

# Written when a run starts, so that a page reloaded mid-run can find it and a
# worker that dies leaves evidence. `build_counts` is cleared here on purpose:
# a started run has produced nothing, and carrying the previous run's numbers
# forward would report them as if they were this one's.
START_BUILD = """
MATCH (v:DocumentVersion {version_id: $version_id})
SET v.build_run_id            = $run_id,
    v.build_state             = 'started',
    v.build_started_at        = $at,
    v.build_changed_at        = $at,
    v.build_extractor_adapter = $extractor_adapter,
    v.build_embedder_adapter  = $embedder_adapter,
    v.build_counts            = '{}',
    v.build_error             = NULL
RETURN v.build_run_id AS run_id
"""

# Guarded on `run_id`: two runs for one edition can overlap when a user queues a
# rebuild, waits, and queues another. The first to finish must not overwrite the
# second's record with its own stale outcome.
FINISH_BUILD = """
MATCH (v:DocumentVersion {version_id: $version_id})
WHERE v.build_run_id = $run_id
SET v.build_state      = $state,
    v.build_changed_at = $at,
    v.build_counts     = $counts,
    v.build_error      = $error
RETURN v.build_run_id AS run_id
"""

READ_BUILD = """
MATCH (v:DocumentVersion {version_id: $version_id})
RETURN v.build_run_id            AS run_id,
       v.build_state             AS state,
       v.build_started_at        AS started_at,
       v.build_changed_at        AS changed_at,
       v.build_extractor_adapter AS extractor_adapter,
       v.build_embedder_adapter  AS embedder_adapter,
       v.build_counts            AS counts,
       v.build_error             AS error
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_build_started(
    tx: ManagedTransaction,
    *,
    version_id: str,
    run_id: str,
    extractor_adapter: str,
    embedder_adapter: str,
) -> None:
    tx.run(
        START_BUILD,
        version_id=version_id,
        run_id=run_id,
        at=_now(),
        extractor_adapter=extractor_adapter,
        embedder_adapter=embedder_adapter,
    ).consume()


def record_build_finished(
    tx: ManagedTransaction, *, version_id: str, run_id: str, counts: dict[str, int]
) -> None:
    tx.run(
        FINISH_BUILD,
        version_id=version_id,
        run_id=run_id,
        state="finished",
        at=_now(),
        counts=json.dumps(counts),
        error=None,
    ).consume()


def record_build_failed(
    tx: ManagedTransaction, *, version_id: str, run_id: str, error: str
) -> None:
    """A failed run keeps whatever it recorded at start.

    The 2026-08-25 timeout wrote 30 of 37 chunks and reported `counts: {}`; the
    chunks were real and are cached, so an edition showing as merely unbuilt
    would be wrong twice.
    """
    tx.run(
        FINISH_BUILD,
        version_id=version_id,
        run_id=run_id,
        state="failed",
        at=_now(),
        counts="{}",
        error=error,
    ).consume()


def read_build(tx: ManagedTransaction, *, version_id: str) -> dict | None:
    """The edition's current or last build, or None if it has never been built."""
    record = tx.run(READ_BUILD, version_id=version_id).single()
    if record is None or record["state"] is None:
        return None
    found = dict(record)
    found["counts"] = json.loads(found["counts"] or "{}")
    return found
