"""What `docker compose up` brings up, asserted against the file rather than a habit.

ADR-028 makes the default stack the whole product. The model server sat behind
`profiles: ["models"]`, and because a profile is only active when it is named,
`docker compose down` did not stop it either — the asymmetry this closes.
"""

import re
import subprocess
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
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


def _resolved(*compose_files: str, env_file: str = "/dev/null") -> dict:
    """What compose actually resolves, not what the file literally says.

    Reading the YAML would test the template `${VAR:-default}` rather than the
    value a container receives, and the default is the whole subject here.
    """
    # --env-file /dev/null is load-bearing. Compose reads ./.env automatically,
    # so a developer who has set EXTRACTOR_ADAPTER there would see their own
    # value and this test would assert nothing about the default. Verified: with
    # it, GRAPH_RENDER_CAP resolves empty, proving .env was not read.
    argv = ["docker", "compose", "--env-file", env_file]
    for path in compose_files:
        argv += ["-f", path]
    argv.append("config")
    out = subprocess.run(argv, capture_output=True, text=True, cwd=REPO_ROOT, check=True)
    return yaml.safe_load(out.stdout)


def test_the_default_stack_extracts_and_embeds_for_real():
    """ADR-028. A default stack whose adapters are `null` cannot fill Review or
    Triage, which is the state this inverts."""
    config = _resolved("docker-compose.yml")
    for name in ("backend", "worker"):
        env = config["services"][name]["environment"]
        assert env["EXTRACTOR_ADAPTER"] == "local", f"{name} would extract nothing"
        assert env["EMBEDDER_ADAPTER"] == "local", f"{name} would embed nothing"


def test_the_default_build_carries_the_embedding_extra():
    """ADR-029. `EMBEDDER_ADAPTER=local` without the extra makes the backend
    refuse to start — `require_sentence_transformers` fires in the lifespan."""
    config = _resolved("docker-compose.yml")
    for name in ("backend", "worker"):
        args = config["services"][name]["build"]["args"]
        assert args["EXTRAS"] == "--extra local-embeddings", f"{name} builds without torch"


def test_an_explicitly_empty_backend_extras_is_honoured(tmp_path):
    """`${BACKEND_EXTRAS:-...}` substituted on empty as well as unset, so a
    developer who wrote `BACKEND_EXTRAS=` in `.env` — following `.env.example`,
    which told them that was the lean build — got the 16.6GB image anyway.
    Verified against the real compose binary before the fix: EXTRAS resolved to
    `--extra local-embeddings` while EXTRACTOR_ADAPTER and EMBEDDER_ADAPTER in
    the same file were honoured.

    The fix is `-` rather than `:-`, written with three dashes because compose
    consumes the first as the operator. Two would silently yield the invalid
    `-extra local-embeddings`, so that is asserted below too.
    """
    env_file = tmp_path / "empty-extras.env"
    env_file.write_text("BACKEND_EXTRAS=\n")

    config = _resolved("docker-compose.yml", env_file=str(env_file))
    for name in ("backend", "worker"):
        assert config["services"][name]["build"]["args"]["EXTRAS"] == "", (
            f"{name} ignores an explicitly empty BACKEND_EXTRAS and builds torch in"
        )


def test_an_absent_backend_extras_still_gets_the_default(tmp_path):
    """The other half of the `-` change, and the half a mis-dashed default
    breaks: with no line at all the extra must still be built in, spelled
    exactly as `uv sync` accepts it."""
    env_file = tmp_path / "no-extras.env"
    env_file.write_text("")

    config = _resolved("docker-compose.yml", env_file=str(env_file))
    for name in ("backend", "worker"):
        assert config["services"][name]["build"]["args"]["EXTRAS"] == "--extra local-embeddings", (
            f"{name}'s default EXTRAS is malformed — `${{VAR--extra ...}}` resolves to "
            "`-extra local-embeddings`, which uv rejects; it needs three dashes"
        )


def test_every_extra_compose_asks_for_actually_exists():
    """The string in compose and the extra in pyproject.toml are two homes for
    one fact, and nothing compared them.

    `--extra local-embeddings` is passed to `uv sync` at image build time. Rename
    or drop that extra and `docker compose up --build` — the one command this
    stack exists to make work — fails for every user, while CI stays green,
    because CI builds only the lean stack and the lean stack passes no extras at
    all. The whole point of ADR-029 is that the default path is the one nothing
    automated builds, so the default path is where a check has to be cheap.

    Verified by renaming the extra in a scratch copy of pyproject.toml: red,
    naming the extra compose asks for and the ones that exist.
    """
    declared = set(
        tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]
    )
    config = _resolved("docker-compose.yml")

    asked_for: set[str] = set()
    for name in ("backend", "worker"):
        asked_for |= set(re.findall(r"--extra[= ]+(\S+)", config["services"][name]["build"]["args"]["EXTRAS"]))

    assert asked_for, (
        "the default stack's EXTRAS names no extra at all — ADR-029 puts "
        "`--extra local-embeddings` there so EMBEDDER_ADAPTER=local has a library"
    )
    missing = sorted(asked_for - declared)
    assert not missing, (
        f"docker-compose.yml builds the default image with `--extra {' --extra '.join(missing)}`, "
        f"but backend/pyproject.toml declares only {sorted(declared)}. `uv sync` fails on an "
        "extra that does not exist, so `docker compose up --build` is broken for every user — "
        "and CI would not catch it, because CI builds the lean stack, which passes no extras."
    )


LEAN = "docker-compose.lean.yml"


def test_the_lean_stack_runs_no_model_services():
    config = _resolved("docker-compose.yml", LEAN)
    for name in MODEL_SERVICES:
        replicas = config["services"][name].get("deploy", {}).get("replicas")
        assert replicas == 0, f"{name} would still start under the lean stack"


def test_the_lean_stack_turns_the_adapters_back():
    """The half `--scale` cannot do. A lean stack still pointing at
    EXTRACTOR_ADAPTER=local looks healthy and fails on every rebuild against a
    model server that is not there."""
    config = _resolved("docker-compose.yml", LEAN)
    for name in ("backend", "worker"):
        env = config["services"][name]["environment"]
        assert env["EXTRACTOR_ADAPTER"] == "null", f"{name} would call a model that is not running"
        assert env["EMBEDDER_ADAPTER"] == "null", f"{name} would embed against a model that is not running"


def test_the_lean_build_drops_the_embedding_extra():
    """Without this the lean stack builds a 16.6GB image and CI's size gate —
    which measures exactly this build — fails."""
    config = _resolved("docker-compose.yml", LEAN)
    for name in ("backend", "worker"):
        assert config["services"][name]["build"]["args"]["EXTRAS"] == ""


def test_the_worker_waits_for_the_model_to_be_pulled():
    """The window this closes is a newcomer's first run.

    `ollama-pull` fetches ~4.9GB. Nothing sequenced it against the worker, so
    the images finished, the UI came up, and a rebuild started in that window
    reached a model server with no model. The worker is the leg that calls the
    model, so the wait belongs there.

    `backend` deliberately does not wait: it never calls the model at boot, and
    `frontend` waits on `backend`, so making the API wait would keep the UI dark
    — Ingest included — for the whole download. A rebuild queued during the pull
    waits in Redis and runs when the worker starts.
    """
    config = _resolved("docker-compose.yml")
    worker = config["services"]["worker"]["depends_on"]

    assert "ollama-pull" in worker, (
        "the worker starts without waiting for the model weights; a rebuild during "
        "the first run's ~4.9GB pull calls a model server that has none"
    )
    assert worker["ollama-pull"]["condition"] == "service_completed_successfully", (
        f"waiting on ollama-pull with condition "
        f"{worker['ollama-pull']['condition']!r} does not mean the pull finished"
    )

    backend = config["services"]["backend"]["depends_on"]
    assert "ollama-pull" not in backend, (
        "the backend now waits on the model pull, which keeps the API — and the "
        "frontend behind it — dark for the length of the download. If that is "
        "wanted, change this test deliberately."
    )


def test_the_lean_worker_does_not_wait_for_a_pull_that_never_runs():
    """`depends_on` merges by union across compose files, so the lean stack has
    to drop this entry with `!override` rather than by omission — otherwise the
    worker waits on `ollama-pull`, which this stack scales to zero replicas and
    which therefore never completes."""
    worker = _resolved("docker-compose.yml", LEAN)["services"]["worker"]["depends_on"]

    assert "ollama-pull" not in worker, (
        "the lean stack's worker waits on ollama-pull, a service it scales to zero "
        "replicas — `docker compose ... -f docker-compose.lean.yml up` would hang"
    )
    assert "redis" in worker, (
        "the !override dropped the redis dependency too; the worker cannot work "
        "without Redis and must still wait for it"
    )
