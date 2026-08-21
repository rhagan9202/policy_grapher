from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_file

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


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
    """Two runs racing over one edition would each drop and rewrite the same
    derived layer, and the second would replay decisions against a half-built one."""
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
