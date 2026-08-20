import pytest

from policy_grapher.config import Settings


@pytest.mark.integration
def test_health_returns_ok(client_with_graph):
    response = client_with_graph.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_read_render_cap_from_environment(monkeypatch):
    monkeypatch.setenv("GRAPH_RENDER_CAP", "42")
    assert Settings().graph_render_cap == 42


def test_settings_default_render_cap_is_300():
    assert Settings(_env_file=None).graph_render_cap == 300


def test_settings_load_an_env_file_over_the_class_defaults(monkeypatch, tmp_path):
    """An env file wins over the class default.

    This used to read the repository's own `.env` and assert it was committed.
    ADR-010 stopped committing it, so that premise is gone — and the test only
    kept passing on machines that happened to have a generated one. It now
    supplies its own file, which pins the mechanism without depending on
    whether the developer has run `scripts/init-env.sh` yet.
    """
    monkeypatch.delenv("NEO4J_URI", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("NEO4J_URI=bolt://neo4j:7687\n")

    # bolt://localhost:7687 is the class default; only seeing the file's value
    # proves the file was actually read.
    assert Settings(_env_file=env_file).neo4j_uri == "bolt://neo4j:7687"
