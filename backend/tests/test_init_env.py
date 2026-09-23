"""`scripts/init-env.sh` refuses to create the one mismatch it cannot warn about.

Driven as a subprocess against a real copy of the repo's `.env.example`, with a
stub `docker` on PATH deciding whether the volume exists. Calling the real docker
would make the result depend on what happens to be on the developer's machine —
which is the failure this guard exists to stop, not a fixture.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "init-env.sh"
EXAMPLE = REPO / ".env.example"


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A throwaway checkout: the script, the example it reads, nothing else."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "init-env.sh")
    shutil.copy(EXAMPLE, tmp_path / ".env.example")
    return tmp_path


def _fake_docker(clone: Path, *, volume_exists: bool) -> Path:
    """A `docker` whose `volume inspect` answers yes or no, and nothing else."""
    bin_dir = clone / "fakebin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        f"[ \"$1\" = volume ] && exit {0 if volume_exists else 1}\n"
        "exit 1\n"
    )
    docker.chmod(0o755)
    return bin_dir


def _run(clone: Path, bin_dir: Path | None, **env_extra) -> subprocess.CompletedProcess:
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin" if bin_dir else "/usr/bin:/bin"}
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(clone / "scripts" / "init-env.sh")],
        capture_output=True,
        text=True,
        env=env,
        # A non-zero exit is the subject of half these tests, not an error.
        check=False,
    )


def test_it_writes_an_env_when_no_volume_survives(clone):
    result = _run(clone, _fake_docker(clone, volume_exists=False))

    assert result.returncode == 0, result.stderr
    written = (clone / ".env").read_text()
    assert "__NEO4J_PASSWORD__" not in written
    assert "NEO4J_AUTH=neo4j/" in written


def test_it_refuses_when_a_neo4j_volume_already_exists(clone):
    result = _run(clone, _fake_docker(clone, volume_exists=True))

    assert result.returncode == 1
    assert not (clone / ".env").exists(), "wrote the .env it said it refused to write"
    # The mechanism, not just the refusal: an operator who is only told "no"
    # deletes the volume or the script, and one of those costs them the graph.
    assert "only reads NEO4J_AUTH when it initialises an empty" in result.stderr
    assert "docker compose down -v" in result.stderr


def test_the_refusal_can_be_overridden_deliberately(clone):
    result = _run(
        clone,
        _fake_docker(clone, volume_exists=True),
        INIT_ENV_ALLOW_STALE_VOLUME="1",
    )

    assert result.returncode == 0, result.stderr
    assert (clone / ".env").exists()


def test_an_existing_env_still_wins_over_the_volume_check(clone):
    """The older guard is the stricter one and keeps precedence.

    A checkout that has both an .env and a volume is the working case, not the
    broken one — they are a matched pair. Reporting the volume there would tell
    a healthy stack it is misconfigured.
    """
    (clone / ".env").write_text("NEO4J_PASSWORD=already-here\n")

    result = _run(clone, _fake_docker(clone, volume_exists=True))

    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert "neo4j-data" not in result.stderr
    assert (clone / ".env").read_text() == "NEO4J_PASSWORD=already-here\n"


def test_no_docker_on_path_does_not_block_setup(clone):
    """A machine without docker cannot have the volume, and must not be stopped."""
    result = _run(clone, None)

    assert result.returncode == 0, result.stderr
    assert (clone / ".env").exists()
