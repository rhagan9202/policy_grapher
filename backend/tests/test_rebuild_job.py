from pathlib import Path

import pytest
from rq import Queue
from rq.job import Job

from policy_grapher.config import Settings
from policy_grapher.ingest import ingest_file
from policy_grapher.jobs.queue import QUEUE_NAME, build_queue
from policy_grapher.jobs.rebuild import rebuild_edition

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_the_queue_is_named_and_carries_the_configured_timeout():
    """A job with no timeout that hangs holds a worker until the process dies.

    The asserted value is injected rather than written as a literal. This
    previously asserted a bare `== 1800`, which passed whether `build_queue`
    read the setting or ignored it and passed its own constant — and went on
    passing when the setting was wrong, saying nothing about the thirty-minute
    default that killed real rebuilds. Injecting proves the wiring.
    """
    settings = Settings(_env_file=None, rebuild_job_timeout_seconds=1234)

    queue = build_queue(settings)

    assert queue.name == QUEUE_NAME
    # Private on purpose: RQ 2.11 exposes the class constant `Queue.DEFAULT_TIMEOUT`
    # but no public accessor for the value a queue was constructed with, and
    # asserting the constant would test RQ rather than this code.
    assert queue._default_timeout == 1234


def test_building_the_queue_does_not_connect():
    """Redis being down must fail only the rebuild routes — the app still boots,
    so constructing the queue cannot reach out to the server."""
    queue = build_queue(
        Settings(_env_file=None, redis_url="redis://not-a-host.invalid:6379/0")
    )

    assert queue is not None


def _ingest_one(driver, database):
    result = ingest_file(driver, database, "514301p.pdf", SAMPLES)
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        {"slug": result.document.slug},
        database_=database,
    )
    return records[0]["id"]


@pytest.mark.integration
def test_the_job_rebuilds_an_edition_and_reports_counts(
    clean_graph, database, monkeypatch, settings_for_container
):
    """Runs the real job function in-process. The null extractor produces no
    obligations, which is the point: this proves the composition works without
    needing a model."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(job_module, "get_settings", lambda: settings_for_container)
    version_id = _ingest_one(clean_graph, database)

    counts = rebuild_edition(version_id)

    assert counts["chunks_written"] > 0
    assert counts["obligations_written"] == 0
    assert "embedded" in counts


@pytest.mark.integration
def test_the_job_records_progress_in_its_metadata(
    clean_graph, database, monkeypatch, settings_for_container, redis_connection
):
    """Progress is polled from job.meta, so it has to round-trip through Redis —
    not merely survive on the in-process object `enqueue` happens to return. A
    status route reads it back with `Job.fetch` from a separate process, so this
    re-fetches from Redis rather than trusting the object still in hand, which
    would pass even if `job.save_meta()` were deleted."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(job_module, "get_settings", lambda: settings_for_container)
    version_id = _ingest_one(clean_graph, database)

    queue = Queue("test-rebuilds", connection=redis_connection, is_async=False)
    job = queue.enqueue(rebuild_edition, version_id=version_id)

    stored = Job.fetch(job.id, connection=redis_connection)
    assert stored.meta["chunks_total"] > 0
    assert stored.meta["chunks_done"] == stored.meta["chunks_total"]


def test_a_truncated_rejection_list_says_how_many_it_left_out(monkeypatch):
    """The list is capped so a pathological run cannot write an unbounded blob
    into Redis, and the cap is right. What was missing is that a reader could
    not tell it had been applied.

    DoDD 5143.01's rebuild reported 20 reasons against 213 refusals — 23 chunks
    rejected and 190 items dropped. Twenty entries with no indication is the
    shape ADR-030 made a silent drop into a defect: the counts are honest and
    the list silently is not.
    """
    from policy_grapher.jobs import rebuild as job_module

    class Job:
        def __init__(self):
            self.meta = {}

        def save_meta(self):
            pass

    job = Job()
    monkeypatch.setattr(job_module, "get_current_job", lambda: job)

    report = job_module._rejection_reporter()
    for i in range(job_module.REPORTED_REJECTIONS + 5):
        report(f"chunk-{i}", "some reason")

    assert len(job.meta["rejections"]) == job_module.REPORTED_REJECTIONS
    assert job.meta["rejections_total"] == job_module.REPORTED_REJECTIONS + 5
