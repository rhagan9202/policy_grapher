"""Where a setting's value actually comes from, and whether the two places agree.

STORY-060, and the reason it exists is worth stating in full. ADR-020 constrains
extraction weights to US-published models and says it is "enforced by a test, not by
a convention". That test asserted on `Settings(_env_file=None).extractor_model`,
which resolves a *developer's shell* — where `EXTRACTOR_MODEL` is unset, so it read
`config.py`'s default and passed. Meanwhile `docker-compose.yml` passed
`qwen3:8b` to every container. The test passed on every machine it ran on while the
deployed configuration violated the ADR on every machine it ran on, for as long as
ADR-020 had existed.

Fixing that one instance was sprint 4. This file closes the class: a setting has two
homes, `config.py` and compose, and nothing was comparing them. Anything asserted
about a default is worthless if the deployment silently supplies another.
"""

import re
from pathlib import Path

import pytest

from policy_grapher.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"

# `NAME: ${NAME:-default}` — the only form compose uses for a defaulted value here.
DEFAULTED = re.compile(r"^\s+([A-Z][A-Z0-9_]*): \$\{[A-Z][A-Z0-9_]*:-([^}]*)\}$", re.MULTILINE)

# Settings fields whose container value is *meant* to differ from the application
# default, each with the reason. Anything not listed here must agree — adding an
# entry is a deliberate act, which is the point.
DELIBERATE_DIFFERENCES = {
    # Service names on the compose network. The application defaults target a host
    # running these on loopback, which is what the extraction ratchet does.
    "extractor_base_url": "reached by service name inside the compose network",
    "redis_url": "reached by service name inside the compose network",
    # ADR-028: the default *stack* carries its models, but config.py's own default
    # stays "null" on purpose, so a bare `uvicorn` run and every test that builds
    # Settings directly keep starting with no model server. Compose overrides this
    # to "local" for backend and worker only — a deployment decision, not a change
    # to the application's fallback.
    "extractor_adapter": "compose defaults to local (ADR-028); config.py's fallback stays null",
    "embedder_adapter": "compose defaults to local (ADR-028); config.py's fallback stays null",
}


def _compose_defaults() -> dict[str, str]:
    """Every `${NAME:-default}` in docker-compose.yml, by variable name."""
    found: dict[str, set[str]] = {}
    for name, default in DEFAULTED.findall(COMPOSE.read_text()):
        found.setdefault(name, set()).add(default)

    conflicting = {n: sorted(v) for n, v in found.items() if len(v) > 1}
    assert not conflicting, (
        f"the same variable is defaulted two different ways in docker-compose.yml: "
        f"{conflicting}. Backend and worker share an image and must not disagree."
    )
    return {name: values.pop() for name, values in found.items()}


def _as_settings_value(field: str, raw: str):
    """Resolve a compose string the way pydantic-settings would."""
    return type(Settings.model_fields[field].default)(
        {"true": True, "false": False}.get(raw.lower(), raw)
    )


@pytest.mark.parametrize("variable,raw", sorted(_compose_defaults().items()))
def test_a_compose_default_agrees_with_the_application_default(variable, raw):
    field = variable.lower()
    if field not in Settings.model_fields:
        pytest.skip(f"{variable} is not a Settings field (build arg, or read by a CLI)")
    if field in DELIBERATE_DIFFERENCES:
        pytest.skip(f"{variable}: {DELIBERATE_DIFFERENCES[field]}")

    assert _as_settings_value(field, raw) == Settings.model_fields[field].default, (
        f"docker-compose.yml defaults {variable} to {raw!r}, but config.py defaults "
        f"{field} to {Settings.model_fields[field].default!r}. A container therefore "
        f"runs on a value nothing tests, which is how ADR-020 was violated for as "
        f"long as it existed. Make them agree, or record the difference in "
        f"DELIBERATE_DIFFERENCES with the reason."
    )


def test_every_deliberate_difference_still_describes_a_real_field():
    """An exception for a setting that no longer exists is an exception nobody reads."""
    stale = sorted(f for f in DELIBERATE_DIFFERENCES if f not in Settings.model_fields)
    assert not stale, f"DELIBERATE_DIFFERENCES names fields that no longer exist: {stale}"
