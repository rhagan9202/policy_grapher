"""Lint is a test, so it runs whether or not anyone remembers to run it.

STORY-032 made a type error fail `npm test` for the same reason: a check that needs a
separate command is a check that stops happening. Needs no container, so it stays in the
`-m "not integration"` subset.
"""

import shutil
import subprocess
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_reports_no_violations():
    # Resolved from PATH rather than run as `python -m ruff`: under `uv run` both work,
    # but a venv synced with `--no-dev` has neither, and "ruff is missing" should not
    # read as "your code has lint errors".
    ruff = shutil.which("ruff")
    assert ruff is not None, (
        "ruff is not on PATH. It ships in the `dev` dependency group — run `uv sync`, "
        "or invoke the suite as `uv run pytest`."
    )

    # No --config: ruff discovers backend/pyproject.toml by walking up from the absolute
    # target path, which is already cwd-independent. Passing --config explicitly makes
    # ruff resolve `src` against the cwd instead, so `policy_grapher` stops being
    # first-party and I001 fires on every import block. Verified, not assumed.
    result = subprocess.run(
        [ruff, "check", "--no-cache", str(BACKEND_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"\n{result.stdout}{result.stderr}"
