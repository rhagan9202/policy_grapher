"""What `docker compose up` brings up, asserted against the file rather than a habit.

ADR-028 makes the default stack the whole product. The model server sat behind
`profiles: ["models"]`, and because a profile is only active when it is named,
`docker compose down` did not stop it either — the asymmetry this closes.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())

MODEL_SERVICES = ("ollama", "ollama-pull")


def test_the_model_services_are_in_the_default_stack():
    """No profile, so `up` starts them and — the point — `down` stops them."""
    for name in MODEL_SERVICES:
        service = COMPOSE["services"][name]
        assert "profiles" not in service, (
            f"{name} carries profiles={service.get('profiles')!r}; a profiled service "
            "is not stopped by a plain `docker compose down`, which is the behaviour "
            "ADR-028 exists to fix"
        )


def test_the_default_stack_is_every_service():
    """A service added later and quietly profiled would not be caught above."""
    profiled = {
        name for name, service in COMPOSE["services"].items() if service.get("profiles")
    }
    assert profiled == set(), f"these services do not start by default: {sorted(profiled)}"
