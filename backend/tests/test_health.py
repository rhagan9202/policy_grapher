from fastapi.testclient import TestClient

from policy_grapher.config import Settings
from policy_grapher.main import app


def test_health_returns_ok():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_read_render_cap_from_environment(monkeypatch):
    monkeypatch.setenv("GRAPH_RENDER_CAP", "42")
    assert Settings().graph_render_cap == 42


def test_settings_default_render_cap_is_300():
    assert Settings(_env_file=None).graph_render_cap == 300
