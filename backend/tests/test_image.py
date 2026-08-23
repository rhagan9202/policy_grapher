"""What the backend image installs, and when.

STORY-052 took the image from 16.6GB to 399MB by moving `sentence-transformers`
into an optional extra. That saving is only real if the *running container* also
declines to install it, and the naive version of this change does not: `uv run`
syncs the project's default groups before running anything, `dev` is a default
group, and `dev` depends on the extra. The image is small and the container
downloads torch on every start — a worse outcome than the 16.6GB image, because
it moves five gigabytes from build time to startup time where nothing caches it.

Reading the Dockerfile rather than running the image is a deliberate trade: the
honest test builds and runs the container, and costs minutes per run for a fact
that lives on one line. This guards that line.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def test_the_container_does_not_sync_dependencies_at_startup():
    dockerfile = DOCKERFILE.read_text()

    assert '"uv", "run"' in dockerfile, (
        "This test guards `uv run`'s implicit sync. If the image stopped invoking "
        "`uv run`, the guard below is no longer the thing that matters — rewrite it."
    )
    assert "UV_NO_SYNC=1" in dockerfile, (
        "backend/Dockerfile runs the app through `uv run`, which syncs the default "
        "dependency groups first. `dev` is one of them and it pulls the "
        "`local-embeddings` extra, so without UV_NO_SYNC=1 every container start "
        "downloads torch into its writable layer. Set it in the ENV block."
    )


def test_the_worker_runs_the_same_way_the_image_was_built():
    """The worker overrides CMD in compose, so it inherits ENV but not the command."""
    compose = COMPOSE.read_text()

    assert '"uv", "run", "rq", "worker"' in compose, (
        "The worker's command changed; confirm it still runs inside the image's "
        "environment rather than re-resolving dependencies of its own."
    )
