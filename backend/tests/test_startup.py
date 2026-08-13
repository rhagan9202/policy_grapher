from pathlib import Path

import pytest
from neo4j import RoutingControl

from policy_grapher.db import clear_graph
from policy_grapher.ingest import ingest_file
from policy_grapher.main import maybe_autoingest

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data"
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


def test_auto_ingest_does_not_rerun_after_the_graph_is_cleared(
    clean_graph, database, autoingest_settings
):
    """Auto-ingest is a startup check, not a reaction to emptiness."""
    maybe_autoingest(clean_graph, autoingest_settings)
    clear_graph(clean_graph, database)
    assert node_count(clean_graph, database) == 0
