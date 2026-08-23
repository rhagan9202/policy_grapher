"""What the automated check runs, and what it cannot quietly stop running.

STORY-051 exists because every check in this project depended on a person
remembering two commands. The risk its sprint plan named is not "there is no CI"
but a worse thing: a CI that reports green over the half of the suite it never
ran. 300 of the 539 backend tests need live Neo4j and Redis, so a workflow that
lost its integration step — by an edit, a merge, or a well-meant speedup — would
still print a green tick over the tests that actually exercise the database.

The defence is structural rather than documentary. Integration runs as its own
step selected by marker, and `pytest` exits 5 when a marker selects nothing
(verified, not assumed), so the step fails rather than passes if the marker is
renamed or the tests disappear. These tests guard that it stays that way.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML parses the workflow under test")

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"{WORKFLOW} is missing — STORY-051 delivered it."
    return yaml.safe_load(WORKFLOW.read_text())


def _run_commands(job: dict) -> list[str]:
    return [step["run"] for step in job["steps"] if "run" in step]


def test_the_workflow_runs_on_every_push_and_pull_request(workflow):
    """Decided at sprint 4: not `main` only. A branch that reports green without
    the database half is the failure mode this story exists to prevent."""
    # YAML 1.1 reads a bare `on:` key as the boolean True. Accept either spelling
    # so the test survives a quoting change that means nothing.
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "the workflow declares no triggers"
    assert "push" in triggers, "must run on push"
    assert "pull_request" in triggers, "must run on pull_request"


def test_the_backend_job_runs_the_integration_half_as_its_own_step(workflow):
    commands = _run_commands(workflow["jobs"]["backend"])

    selects_integration = [c for c in commands if "-m integration" in c]
    assert selects_integration, (
        "No step selects `-m integration`. Folding integration back into a single "
        "`pytest` run is not equivalent: as its own step it fails with exit 5 when "
        "the marker selects nothing, which is what stops the database half going "
        "quiet without anyone noticing."
    )


def test_the_frontend_suite_runs_too(workflow):
    """`npm test` is three gates chained — eslint, tsc, vitest — so running the
    command is running all three. Losing it loses all three at once."""
    commands = _run_commands(workflow["jobs"]["frontend"])

    assert any("npm test" in c for c in commands), "no step runs the frontend suite"


def test_every_job_checks_the_repository_out_before_running_anything(workflow):
    for name, job in workflow["jobs"].items():
        uses = [step.get("uses", "") for step in job["steps"]]
        assert any(u.startswith("actions/checkout") for u in uses), (
            f"job {name!r} runs without checking the repository out"
        )
