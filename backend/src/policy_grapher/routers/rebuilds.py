"""Starting and polling a derived-layer rebuild.

Everything knowable before the work starts is checked here, in the request: an
unknown edition, a source file the backend cannot read, a run already in flight.
STORY-048 requires a missing source to be a 4xx naming the edition, and a job
that dies ten seconds later reporting the same thing would satisfy the letter of
that and not its intent.
"""

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
from policy_grapher.links.rebuild import MissingSourceError, resolve_source
from policy_grapher.models import RebuildRequest, RebuildStarted, RebuildStatus

router = APIRouter(tags=["rebuilds"])

EDITION = """
MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion {version_id: $version_id})
RETURN v.source_uri AS source_uri
"""

# Candidates are looked up by version id alone, without a slug: the whole point
# of naming them is that they belong to *other* documents — the higher-tier
# issuances this edition may implement.
CANDIDATE = """
MATCH (v:DocumentVersion {version_id: $version_id})
RETURN v.version_id AS version_id
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
    body: RebuildRequest | None = None,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    queue: Queue = Depends(get_queue),
    principal: Principal = Depends(require_principal),
) -> RebuildStarted:
    """Queue a rebuild of one edition's derived layer.

    **Omitting `candidate_version_ids` means no proposals are generated.** The
    rebuild still re-chunks, re-extracts, re-embeds and replays every recorded
    decision, but `IMPLEMENTS_PROPOSED` edges are only written between this
    edition's obligations and the editions the caller names, so `GET
    /review/queue` stays empty until a caller names some. The route does not
    pick them itself because it cannot: nothing in the graph records which
    documents are higher-tier — ADR-015 says so explicitly when it drops tier
    distance from triage ranking — so any guess here would be invented policy.

    The body is optional; an empty POST is a rebuild with no proposals.

    **Known limitation.** Rebuilding edition V `DETACH DELETE`s V's obligations,
    and that takes with it any `IMPLEMENTS_PROPOSED` edge pointing *at* V that a
    rebuild of some other edition W created. So rebuilding a higher-tier edition
    silently empties the review queue of proposals against it, and they come back
    only when W is rebuilt again. Approvals survive — `:LinkDecision` is canonical
    and is replayed (ADR-014) — but pending proposals do not.
    """
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

    try:
        resolve_source(version_id, records[0]["source_uri"])
    except MissingSourceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    candidate_version_ids = list(body.candidate_version_ids) if body else []
    for candidate in candidate_version_ids:
        found, _, _ = driver.execute_query(
            CANDIDATE,
            {"version_id": candidate},
            database_=settings.neo4j_database,
            routing_=RoutingControl.READ,
        )
        if not found:
            raise HTTPException(
                status_code=404,
                detail=f"No candidate edition {candidate!r}.",
            )

    try:
        existing = _in_flight(queue, version_id)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Rebuild {existing} is already running for {version_id!r}.",
            )
        # `result_ttl` belongs here and not on the queue: RQ's Queue constructor
        # swallows unknown keywords, so setting it there is accepted and ignored.
        # It is much longer than the job timeout on purpose — a finished run's
        # result is the only record of what it produced, and on RQ's 500-second
        # default a legitimate 1800-second run expires eight minutes after it
        # lands, leaving the poll route to answer 404 for a run that succeeded.
        job = queue.enqueue(
            rebuild_edition,
            version_id=version_id,
            candidate_version_ids=candidate_version_ids,
            result_ttl=settings.rebuild_result_ttl_seconds,
        )
    except RedisError as exc:
        raise _unavailable() from exc

    return RebuildStarted(
        run_id=job.id,
        version_id=version_id,
        candidate_version_ids=candidate_version_ids,
    )


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

    # One fetch, not two: `latest_result()` is a Redis round-trip, and both
    # `counts` and `error` come out of the same Result. It is None when the run
    # has not finished — and also when a finished run's Result has already
    # expired, which is why the failed branch cannot assume one exists: a 500
    # from the route whose whole job is to explain a failure is the worst
    # possible answer.
    latest = job.latest_result()
    returned = latest.return_value if latest is not None else None

    return RebuildStatus(
        run_id=job.id,
        version_id=job.kwargs.get("version_id", ""),
        state=job.get_status(),
        chunks_done=job.meta.get("chunks_done", 0),
        chunks_total=job.meta.get("chunks_total", 0),
        counts=returned if isinstance(returned, dict) else {},
        rejections=job.meta.get("rejections", []),
        error=(latest.exc_string if latest is not None else None) if job.is_failed else None,
    )
