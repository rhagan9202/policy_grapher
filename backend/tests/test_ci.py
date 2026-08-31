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

import re
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


def _compose_build_command(job: dict) -> str:
    """The one step that builds, isolated from every other `run:` block.

    The two tests below used to join every command in the job and search the
    blob. Both were unfailable, for the same reason: the size-gate step's own
    text contains the strings they looked for. Its error message names
    "docker-compose.lean.yml", so stripping the `-f` flags from every step left
    the lean-stack assertion green while CI built the ~16.6GB default images;
    its loop over `policy_grapher-backend` and `policy_grapher-worker` contains
    "backend" and "worker" as substrings, so a build step naming only
    `frontend` left the coverage assertion green too. Both were verified green
    under exactly those mutations before this helper existed.

    Scoping to the build command is what makes them able to fail. A word-boundary
    match on "build" rather than a contiguous "docker compose build", because
    compose requires any `-f` flags to sit between those two words.
    """
    builds = [
        c for c in _run_commands(job) if "docker compose" in c and re.search(r"\bbuild\b", c)
    ]
    assert len(builds) == 1, (
        f"expected exactly one compose build step in the job, found {len(builds)}: "
        f"{builds!r}. These assertions describe one build command; if the job now "
        "has several, scope them deliberately rather than joining the steps back "
        "together — that is the shape that made both of them unfailable."
    )
    return builds[0]


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


def test_the_workflow_proves_the_stack_builds(workflow):
    """STORY-059. The last Definition-of-Done gate nothing automated covered.

    "Runs under `docker compose up` from a clean checkout" was verified by a person
    running one command, in a sprint that changed the backend image, both `uv sync`
    stages and the build arguments for two services. Building through compose rather
    than `docker build` is the point: the build arguments and the two services that
    share the image are declared in compose and nowhere else.
    """
    commands = _run_commands(workflow["jobs"]["compose"])

    # A literal "docker compose build" substring does not survive `-f` file flags
    # (`docker compose -f a.yml -f b.yml build ...`), which docker compose requires
    # between "compose" and "build" — and Task 6 (STORY-080) added a second `-f` to
    # point this job at the lean stack. The check follows the subcommand rather than
    # a contiguous string so a legitimate `-f` does not read as "no step builds".
    assert any(
        "docker compose" in c and re.search(r"\bbuild\b", c) for c in commands
    ), "no step builds the images through compose"


def test_the_compose_build_covers_every_service_that_is_built(workflow):
    """A job that builds one of three images proves a third of what it claims.

    Read from the build command, not the job's joined text. Joined, this could
    not fail: the size-gate step loops over `policy_grapher-backend` and
    `policy_grapher-worker`, so "backend" and "worker" were present as
    substrings however few services the build step actually named. Verified
    green against a build step naming `frontend` alone before this change.
    """
    built = {
        name
        for name, service in yaml.safe_load(
            (REPO_ROOT / "docker-compose.yml").read_text()
        )["services"].items()
        if "build" in service
    }
    command = _compose_build_command(workflow["jobs"]["compose"])
    # Split on whitespace and compare whole arguments: a substring test would
    # read `policy_grapher-backend` as "backend" again, one step further along.
    named = set(command.split())

    missing = sorted(s for s in built if s not in named)
    assert not missing, (
        f"docker-compose.yml builds {sorted(built)} but the compose job's build "
        f"step, {command!r}, never names {missing}. Either build them or drop "
        "them from compose."
    )


def test_the_compose_job_measures_the_lean_stack(workflow):
    """ADR-028 moved the models into the default stack, so the default image is
    now ~16.6GB and the 1GB gate below would fail on every push. The gate exists
    to prove the *lean* image has not silently regrown, and that purpose survives
    the default changing — but only if the job actually builds the lean stack.

    Asserted against the build command alone, not the job's joined text: the
    size-gate step's error message names `docker-compose.lean.yml` too, so the
    joined form said nothing about what CI builds.
    """
    command = _compose_build_command(workflow["jobs"]["compose"])

    assert "docker-compose.lean.yml" in command, (
        f"the compose job's build step is {command!r}, which builds the default "
        "stack, whose images are ~16.6GB — the size gate would fail on every push"
    )



def test_ci_runs_the_extraction_gate_against_a_real_model():
    """The gate skips silently unless CI configures an adapter with floors.

    Before this, `extractor_adapter` defaulted to "null", FLOORS had no "null"
    key, and the gate took its first skip branch on every push — green because
    nothing checked, for the whole of DI-2.
    """
    workflow = WORKFLOW.read_text()
    assert "EXTRACTOR_ADAPTER: local" in workflow, (
        "CI does not configure a real extractor, so the extraction gate skips"
    )
    assert "llama3.2:3b" in workflow, "CI does not pull the model the gate needs"
