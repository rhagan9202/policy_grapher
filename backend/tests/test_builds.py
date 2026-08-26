"""The durable record of what a rebuild did — STORY-082.

An edition showing zero obligations has three possible causes needing different
actions: nobody ever built it, it was built with the `null` extractor which
writes chunks and no obligations by design (ADR-028), or a run died partway.
Nothing durable told them apart. `RebuildStatus` already reported the adapters
for exactly this reason, and its comment says so — but only for the lifetime of
one poll, against a run id that lived in React state and vanished on reload.

Recorded in the graph rather than RQ because RQ is deliberately forgetful:
`rebuild_result_ttl_seconds` expires a result after a day, so it can never
answer "was this edition ever built".
"""

import json

import pytest

from policy_grapher.builds import (
    read_build,
    record_build_failed,
    record_build_finished,
    record_build_started,
)

VERSION = "dodd-5000-01@2020-09-09"


@pytest.fixture
def version(clean_graph, database):
    clean_graph.execute_query(
        "MERGE (d:Document {slug: 'dodd-5000-01', name: 'DoDD 5000.01'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        {"vid": VERSION},
        database_=database,
    )
    return clean_graph


@pytest.mark.integration
def test_an_edition_nobody_built_has_no_build_record(version, database):
    with version.session(database=database) as session:
        found = session.execute_read(read_build, version_id=VERSION)

    assert found is None


@pytest.mark.integration
def test_a_run_is_recorded_when_it_starts_not_when_it_finishes(version, database):
    """The criterion the story was repaired for at planning.

    Recording only on completion leaves nothing for a reloaded page to
    re-attach to, and nothing to distinguish a worker that died from an edition
    nobody ever built — which is the whole point of the story.
    """
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-1",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert found["run_id"] == "run-1"
    assert found["state"] == "started"
    assert found["extractor_adapter"] == "local"
    assert found["embedder_adapter"] == "local"
    assert found["started_at"]
    assert found["counts"] == {}


@pytest.mark.integration
def test_a_finished_run_records_what_it_wrote(version, database):
    counts = {"chunks_written": 37, "obligations_written": 113, "embedded": 37}
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-1",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        session.execute_write(
            record_build_finished, version_id=VERSION, run_id="run-1", counts=counts
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert found["state"] == "finished"
    assert found["counts"] == counts
    assert found["error"] is None


@pytest.mark.integration
def test_a_failed_run_records_why(version, database):
    """The 2026-08-25 timeout wrote 30 of 37 chunks and reported `counts: {}`.
    A screen that showed that edition as merely unbuilt would be wrong twice:
    the run happened, and the chunks it paid for are cached."""
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-1",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        session.execute_write(
            record_build_failed,
            version_id=VERSION,
            run_id="run-1",
            error="Task exceeded maximum timeout value (28800 seconds)",
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert found["state"] == "failed"
    assert "28800" in found["error"]


@pytest.mark.integration
def test_a_later_run_replaces_the_record_rather_than_appending(version, database):
    """Scope is the current or last build, not full run history. A log of every
    run needs a retention decision this story does not take."""
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-1",
            extractor_adapter="null",
            embedder_adapter="null",
        )
        session.execute_write(
            record_build_finished, version_id=VERSION, run_id="run-1", counts={"a": 1}
        )
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-2",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert found["run_id"] == "run-2"
    assert found["state"] == "started"
    assert found["extractor_adapter"] == "local"
    # The previous run's counts must not survive onto a run that has not
    # produced any, or a started run would report the last one's numbers.
    assert found["counts"] == {}


@pytest.mark.integration
def test_a_stale_update_from_an_overtaken_run_is_ignored(version, database):
    """Two runs for one edition can overlap: a user queues a rebuild, it is slow,
    they queue another. The first finishing afterwards must not overwrite the
    second's record with its own stale result."""
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-1",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="run-2",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        session.execute_write(
            record_build_finished,
            version_id=VERSION,
            run_id="run-1",
            counts={"chunks_written": 1},
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert found["run_id"] == "run-2"
    assert found["state"] == "started"


@pytest.mark.integration
def test_the_counts_survive_a_round_trip_as_json(version, database):
    """Neo4j stores no maps on a property, so counts go through JSON. If that
    ever silently became a string the screen would render one."""
    with version.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=VERSION,
            run_id="r",
            extractor_adapter="local",
            embedder_adapter="local",
        )
        session.execute_write(
            record_build_finished,
            version_id=VERSION,
            run_id="r",
            counts={"chunks_written": 3},
        )
        found = session.execute_read(read_build, version_id=VERSION)

    assert isinstance(found["counts"], dict)
    assert found["counts"]["chunks_written"] == 3
    assert not isinstance(found["counts"], str)
    json.dumps(found["counts"])


# --- what the versions route reports (STORY-082 AC2) ---------------------------


@pytest.mark.integration
def test_the_versions_route_reports_an_unbuilt_edition_as_unbuilt(client_with_auth):
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    driver.execute_query(
        "MERGE (d:Document {slug: 'never-built', name: 'Never Built'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'nb@2020-01-01', "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        database_=database,
    )

    body = client_with_auth.get("/documents/never-built/versions").json()

    assert body[0]["build_state"] is None
    assert body[0]["build_counts"] == {}


@pytest.mark.integration
def test_the_versions_route_reports_what_a_build_produced(client_with_auth):
    """AC4's data. `null` writes chunks and no obligations by design, and a
    screen cannot say so unless the adapter that ran is on the record."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    driver.execute_query(
        "MERGE (d:Document {slug: 'built', name: 'Built'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'b@2020-01-01', "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        database_=database,
    )
    with driver.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id="b@2020-01-01",
            run_id="run-9",
            extractor_adapter="null",
            embedder_adapter="null",
        )
        session.execute_write(
            record_build_finished,
            version_id="b@2020-01-01",
            run_id="run-9",
            counts={"chunks_written": 41, "obligations_written": 0},
        )

    body = client_with_auth.get("/documents/built/versions").json()

    assert body[0]["build_state"] == "finished"
    assert body[0]["build_run_id"] == "run-9"
    assert body[0]["build_extractor_adapter"] == "null"
    assert body[0]["build_counts"]["chunks_written"] == 41
    assert body[0]["build_counts"]["obligations_written"] == 0
    assert body[0]["build_changed_at"]


@pytest.mark.integration
def test_the_versions_route_reports_a_run_still_in_flight(client_with_auth):
    """AC5's data: the run id a reloaded page re-attaches to."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    driver.execute_query(
        "MERGE (d:Document {slug: 'running', name: 'Running'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'r@2020-01-01', "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        database_=database,
    )
    with driver.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id="r@2020-01-01",
            run_id="run-live",
            extractor_adapter="local",
            embedder_adapter="local",
        )

    body = client_with_auth.get("/documents/running/versions").json()

    assert body[0]["build_state"] == "started"
    assert body[0]["build_run_id"] == "run-live"
