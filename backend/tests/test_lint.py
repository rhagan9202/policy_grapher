"""Lint is a test, so it runs whether or not anyone remembers to run it.

STORY-032 made a type error fail `npm test` for the same reason: a check that needs a
separate command is a check that stops happening. Needs no container, so it stays in the
`-m "not integration"` subset.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_ruff_reports_no_violations():
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--no-cache", str(BACKEND_ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"\n{result.stdout}{result.stderr}"
