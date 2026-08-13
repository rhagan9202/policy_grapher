from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from neo4j import RoutingControl

from policy_grapher import main
from policy_grapher.config import get_settings
from policy_grapher.db import clear_graph
from policy_grapher.ingest import ingest_file
from policy_grapher.main import maybe_autoingest

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "samples"
SAMPLE = "dod_policy_references_08122026.csv"


def node_count(driver, database) -> int:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document) RETURN count(d) AS n",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["n"]


@pytest.fixture
def autoingest_settings(settings_for_container):
    return settings_for_container.model_copy(
        update={"data_dir": REPO_DATA, "auto_ingest": True, "sample_csv": SAMPLE}
    )


def test_an_empty_graph_is_populated(clean_graph, database, autoingest_settings):
    result = maybe_autoingest(clean_graph, autoingest_settings)

    assert result is not None
    assert result.nodes_created == 438
    assert node_count(clean_graph, database) == 438


def test_a_populated_graph_is_left_alone(clean_graph, database, autoingest_settings):
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    result = maybe_autoingest(clean_graph, autoingest_settings)

    assert result is None
    assert node_count(clean_graph, database) == 438


def test_auto_ingest_can_be_disabled(clean_graph, database, autoingest_settings):
    settings = autoingest_settings.model_copy(update={"auto_ingest": False})
    result = maybe_autoingest(clean_graph, settings)

    assert result is None
    assert node_count(clean_graph, database) == 0


def test_a_missing_sample_file_does_not_prevent_startup(
    clean_graph, database, autoingest_settings
):
    settings = autoingest_settings.model_copy(update={"sample_csv": "absent.csv"})
    assert maybe_autoingest(clean_graph, settings) is None
    assert node_count(clean_graph, database) == 0


def test_a_graph_emptied_at_runtime_stays_empty_on_the_next_request(
    clean_graph, settings_for_container, database, driver, monkeypatch
):
    """STORY-029: auto-ingest is a startup check, not a reaction to
    emptiness. A graph emptied at runtime (e.g. a future POST /reset)
    must stay empty across subsequent requests, because lifespan's
    auto-ingest call runs exactly once, at process boot, and no other
    code path re-invokes it.
    """
    settings = settings_for_container.model_copy(
        update={"data_dir": REPO_DATA, "auto_ingest": True, "sample_csv": SAMPLE}
    )

    get_settings.cache_clear()
    monkeypatch.setattr(main, "get_settings", lambda: settings)

    with TestClient(main.app) as client:
        # Entering the client runs lifespan, which auto-ingests into the
        # empty graph left by `clean_graph`.
        assert node_count(driver, database) == 438

        # Simulate a runtime reset, out of band -- not through the app.
        clear_graph(driver, database)
        assert node_count(driver, database) == 0

        # A subsequent request must not re-trigger auto-ingest.
        response = client.get("/health")
        assert response.status_code == 200
        assert node_count(driver, database) == 0

    get_settings.cache_clear()
