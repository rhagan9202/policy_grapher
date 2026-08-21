from pathlib import Path

import pytest
from rq import Queue

from policy_grapher.config import Settings
from policy_grapher.ingest import ingest_file
from policy_grapher.jobs.queue import QUEUE_NAME, build_queue
from policy_grapher.jobs.rebuild import rebuild_edition

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


def test_the_queue_is_named_and_carries_a_timeout():
    """A job with no timeout that hangs holds a worker until the process dies."""
    queue = build_queue(Settings(_env_file=None))

    assert queue.name == QUEUE_NAME
    # Private on purpose: RQ 2.11 exposes the class constant `Queue.DEFAULT_TIMEOUT`
    # but no public accessor for the value a queue was constructed with, and
    # asserting the constant would test RQ rather than this code.
    assert queue._default_timeout == 1800


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
    """Progress is polled from job.meta, so it has to be written there while the
    job runs — not merely handed to a callback that discards it."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(job_module, "get_settings", lambda: settings_for_container)
    version_id = _ingest_one(clean_graph, database)

    queue = Queue("test-rebuilds", connection=redis_connection, is_async=False)
    job = queue.enqueue(rebuild_edition, version_id=version_id)

    assert job.meta["chunks_total"] > 0
    assert job.meta["chunks_done"] == job.meta["chunks_total"]
