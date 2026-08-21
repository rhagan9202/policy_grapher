"""Starting and polling a derived-layer rebuild.

Everything knowable before the work starts is checked here, in the request: an
unknown edition, a source file the backend cannot read, a run already in flight.
STORY-048 requires a missing source to be a 4xx naming the edition, and a job
that dies ten seconds later reporting the same thing would satisfy the letter of
that and not its intent.
"""

from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException
from neo4j import Driver, RoutingControl
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.registry import StartedJobRegistry

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver, get_queue
from policy_grapher.jobs.rebuild import rebuild_edition
from policy_grapher.models import RebuildStarted, RebuildStatus

router = APIRouter(tags=["rebuilds"])

EDITION = """
MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion {version_id: $version_id})
RETURN v.source_uri AS source_uri
"""


def _in_flight(queue: Queue, version_id: str) -> str | None:
    """The run id already working on this edition, if any.

    Scans the queued and started registries rather than keeping a lock key: a
    lock has to be released, and a worker killed mid-run would leave one behind
    that nothing clears. The registries are the queue's own truth, and there are
    never many jobs here.
    """
    ids = list(queue.get_job_ids()) + list(StartedJobRegistry(queue=queue).get_job_ids())
    for job_id in ids:
        job = queue.fetch_job(job_id)
        if job is not None and job.kwargs.get("version_id") == version_id:
            return job_id
    return None


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="The rebuild queue is unreachable. Every other route is unaffected.",
    )


@router.post(
    "/documents/{slug}/versions/{version_id}/rebuild",
    response_model=RebuildStarted,
    status_code=202,
)
def start_rebuild(
    slug: str,
    version_id: str,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    queue: Queue = Depends(get_queue),
    principal: Principal = Depends(require_principal),
) -> RebuildStarted:
    records, _, _ = driver.execute_query(
        EDITION,
        {"slug": slug, "version_id": version_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No edition {version_id!r} on document {slug!r}.",
        )

    source = Path(unquote(urlparse(records[0]["source_uri"]).path))
    if not source.is_file():
        raise HTTPException(
            status_code=409,
            detail=(
                f"{version_id!r} was read from {source}, which is not readable now. "
                f"Re-chunking needs the original document."
            ),
        )

    try:
        existing = _in_flight(queue, version_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Rebuild {existing} is already running for {version_id!r}.",
            )
        job = queue.enqueue(rebuild_edition, version_id=version_id)
    except RedisError as exc:
        raise _unavailable() from exc

    return RebuildStarted(run_id=job.id, version_id=version_id)


@router.get("/rebuilds/{run_id}", response_model=RebuildStatus)
def read_rebuild(
    run_id: str,
    queue: Queue = Depends(get_queue),
    principal: Principal = Depends(require_principal),
) -> RebuildStatus:
    try:
        job = Job.fetch(run_id, connection=queue.connection)
    except NoSuchJobError as exc:
        raise HTTPException(status_code=404, detail=f"No rebuild run {run_id!r}.") from exc
    except RedisError as exc:
        raise _unavailable() from exc

    return RebuildStatus(
        run_id=job.id,
        version_id=job.kwargs.get("version_id", ""),
        state=job.get_status(),
        chunks_done=job.meta.get("chunks_done", 0),
        chunks_total=job.meta.get("chunks_total", 0),
        counts=job.result if isinstance(job.result, dict) else {},
        error=job.latest_result().exc_string if job.is_failed else None,
    )
