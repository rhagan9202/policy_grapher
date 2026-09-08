"""Run a canary replay against the current extractor and print what moved.

The functions in `replay.py` are the primitives; this is the thing a person
actually runs after a prompt change, so that using the feature does not mean
re-deriving Step 5's recording script by hand every time.

Usage (after Tasks 1-4, so the runtime is pinned and the decoding mode is
settled):

    cd backend && EXTRACTOR_ADAPTER=local EXTRACTOR_MODEL=llama3.1:8b \\
        uv run python -m canary.run

Loads the committed `chunks.json` and `baseline.json`, replays the same
`extractor.extract()` call `record()` used to build the baseline, and prints
the diff plus a one-line summary. Deliberately not a pass/fail gate — see
`replay.py`'s module docstring; a diff is information a human reads, not a
check a script enforces, so this always exits 0.
"""

import json
import sys
from pathlib import Path

# Lets this run standalone (`python -m canary.run`, or the file invoked
# directly) without depending on pytest's own sys.path setup — pytest adds
# `backend/tests` to sys.path itself (via `pythonpath = ["src"]` plus its
# no-`__init__.py` test discovery), but a plain `uv run python -m canary.run`
# gets no such help. Inserting the parent of this package (`backend/tests`)
# makes `canary` importable as a top-level package either way; when pytest
# collects this module the insert is a harmless duplicate of what it already
# did.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canary.replay import FIXTURES, diff, record
from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor


def main() -> None:
    chunks = json.loads((FIXTURES / "chunks.json").read_text())
    baseline_raw = json.loads((FIXTURES / "baseline.json").read_text())
    baseline = {key: value for key, value in baseline_raw.items() if key != "_meta"}

    extractor = build_extractor(Settings())
    current = record(extractor, chunks)

    result = diff(baseline, current)
    print(
        json.dumps(
            {
                "baseline_meta": baseline_raw.get("_meta"),
                "moved": len(result["moved"]),
                "added": len(result["added"]),
                "removed": len(result["removed"]),
            },
            indent=2,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
