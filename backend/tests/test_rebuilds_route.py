from pathlib import Path

import pytest
from rq import Queue

from policy_grapher.ingest import ingest_file
from policy_grapher.jobs.rebuild import rebuild_edition

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

# A queue of its own for the tests that run a job synchronously. `queue.empty()`
# in the fixtures clears the queued list and nothing else, so a job that has
# finished or failed still sits in StartedJobRegistry / FailedJobRegistry — on
# the route's own queue that would make the next test's edition look in-flight
# and turn its 202 into a 409. Separate name, no collision.
SYNC_QUEUE = "rebuilds-run-in-process"


def _ingest(client, filename="514301p.pdf"):
    driver = client.app.state.driver
    database = client.app.state.settings.neo4j_database
    result = ingest_file(driver, database, filename, SAMPLES)
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        {"slug": result.document.slug},
        database_=database,
    )
    return result.document.slug, records[0]["id"]


@pytest.mark.integration
def test_starting_a_rebuild_returns_a_run_id(client_with_auth):
    slug, version_id = _ingest(client_with_auth)

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 202
    assert response.json()["run_id"]
    assert response.json()["version_id"] == version_id


@pytest.mark.integration
def test_an_unknown_edition_is_a_404_naming_it(client_with_auth):
    slug, _ = _ingest(client_with_auth)

    response = client_with_auth.post(f"/documents/{slug}/versions/not-an-edition/rebuild")

    assert response.status_code == 404
    assert "not-an-edition" in response.json()["detail"]


@pytest.mark.integration
def test_an_unreadable_source_is_a_409_naming_the_file(client_with_auth, tmp_path):
    """STORY-048: a 4xx from the route, not a job that dies later. A dead job
    reporting 'file not found' meets the letter of that and not its intent."""
    slug, version_id = _ingest(client_with_auth)
    missing = tmp_path / "vanished.pdf"
    client_with_auth.app.state.driver.execute_query(
        "MATCH (v:DocumentVersion {version_id: $id}) SET v.source_uri = $uri",
        {"id": version_id, "uri": f"file://{missing}"},
        database_=client_with_auth.app.state.settings.neo4j_database,
    )

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 409
    assert "vanished.pdf" in response.json()["detail"]


@pytest.mark.integration
def test_a_second_rebuild_of_the_same_edition_is_refused(client_with_auth):
    """What the 409 actually buys: a second caller is told the work is already
    happening instead of queueing a duplicate run that would redo it from
    scratch. It is not a lock — there is a window between the check and the
    enqueue — and it does not need to be: every mutation lands in one
    `execute_write` with deterministic ids, so a race that slipped through would
    rewrite the same rows rather than corrupt anything."""
    slug, version_id = _ingest(client_with_auth)
    first = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild"
    ).json()["run_id"]

    response = client_with_auth.post(f"/documents/{slug}/versions/{version_id}/rebuild")

    assert response.status_code == 409
    assert first in response.json()["detail"]


@pytest.mark.integration
def test_a_started_run_can_be_polled(client_with_auth):
    slug, version_id = _ingest(client_with_auth)
    run_id = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild"
    ).json()["run_id"]

    response = client_with_auth.get(f"/rebuilds/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["version_id"] == version_id
    assert body["state"] in {"queued", "started", "finished"}


@pytest.mark.integration
def test_an_unknown_run_is_a_404(client_with_auth):
    assert client_with_auth.get("/rebuilds/not-a-run").status_code == 404


@pytest.mark.integration
def test_both_routes_require_a_principal(client_with_graph):
    assert client_with_graph.post("/documents/x/versions/y/rebuild").status_code == 401
    assert client_with_graph.get("/rebuilds/anything").status_code == 401


@pytest.mark.integration
def test_candidate_editions_are_accepted_and_passed_to_the_job(client_with_auth):
    """The proposals half of STORY-048. Naming candidates is what makes
    `propose_links` run at all, so the enqueued job has to carry them — a 202
    that echoes them back while enqueueing nothing would look identical from
    outside and leave the review queue empty forever."""
    slug, version_id = _ingest(client_with_auth)
    _, candidate_id = _ingest(client_with_auth, "500088p.pdf")

    response = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild",
        json={"candidate_version_ids": [candidate_id]},
    )

    assert response.status_code == 202
    assert response.json()["candidate_version_ids"] == [candidate_id]
    job = client_with_auth.app.state.queue.fetch_job(response.json()["run_id"])
    assert job.kwargs["candidate_version_ids"] == [candidate_id]


@pytest.mark.integration
def test_an_unknown_candidate_edition_is_a_404_naming_it(client_with_auth):
    """Validated before anything is enqueued, like every other check here: a job
    that dies later on a candidate the caller mistyped is the failure mode this
    route exists to prevent."""
    slug, version_id = _ingest(client_with_auth)

    response = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild",
        json={"candidate_version_ids": ["not-an-edition"]},
    )

    assert response.status_code == 404
    assert "not-an-edition" in response.json()["detail"]
    assert client_with_auth.app.state.queue.count == 0


@pytest.mark.integration
def test_a_finished_run_reports_its_counts(client_with_auth, monkeypatch, redis_connection):
    """The finished half of the poll route. Every other test here leaves the job
    queued, so `counts` was never populated by anything. A synchronous queue runs
    the real job in this process, with no worker."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(
        job_module, "get_settings", lambda: client_with_auth.app.state.settings
    )
    _slug, version_id = _ingest(client_with_auth)

    queue = Queue(SYNC_QUEUE, connection=redis_connection, is_async=False)
    job = queue.enqueue(rebuild_edition, version_id=version_id)

    response = client_with_auth.get(f"/rebuilds/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "finished"
    assert body["counts"]["chunks_written"] > 0
    assert body["error"] is None


@pytest.mark.integration
def test_a_failed_run_reports_its_error(
    client_with_auth, monkeypatch, redis_connection, tmp_path
):
    """The failed half. Enqueued directly rather than through the route, which
    would refuse this with a 409 before a job existed — the point is what a
    poller sees when the job itself raises."""
    from policy_grapher.jobs import rebuild as job_module

    monkeypatch.setattr(
        job_module, "get_settings", lambda: client_with_auth.app.state.settings
    )
    _slug, version_id = _ingest(client_with_auth)
    missing = tmp_path / "vanished.pdf"
    client_with_auth.app.state.driver.execute_query(
        "MATCH (v:DocumentVersion {version_id: $id}) SET v.source_uri = $uri",
        {"id": version_id, "uri": f"file://{missing}"},
        database_=client_with_auth.app.state.settings.neo4j_database,
    )

    queue = Queue(SYNC_QUEUE, connection=redis_connection, is_async=False)
    job = queue.enqueue(rebuild_edition, version_id=version_id)

    response = client_with_auth.get(f"/rebuilds/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "failed"
    assert "MissingSourceError" in body["error"]
    assert "vanished.pdf" in body["error"]


@pytest.mark.integration
def test_an_enqueued_run_keeps_its_result_for_a_day(client_with_auth):
    """The result is the only record of what a run produced. On RQ's 500-second
    default a legitimate 1800-second run's counts expire eight minutes after they
    land, and `GET /rebuilds/{run_id}` then answers 404 — the same answer it
    gives for a run id that never existed. Asserted on the job because RQ's Queue
    constructor silently discards a `result_ttl` keyword; it is a per-job value."""
    slug, version_id = _ingest(client_with_auth)

    run_id = client_with_auth.post(
        f"/documents/{slug}/versions/{version_id}/rebuild"
    ).json()["run_id"]

    job = client_with_auth.app.state.queue.fetch_job(run_id)
    assert job.result_ttl == 86400
