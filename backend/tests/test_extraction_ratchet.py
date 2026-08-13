"""Extraction quality as a number that fails the build when it regresses.

Floors are what the parser achieved when written, rounded down to the nearest 5%.
They may only be raised. Raising one is the correct response to improving the
parser; lowering one needs a reason in the commit message.
"""

import ast
import csv
from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
CORPUS = SAMPLES / "dod_policy_references_08122026.csv"

# fixture -> (corpus name, minimum fraction of that document's references we must find)
FLOORS = {
    "500001p.pdf": ("DoDD 5000.01", 1.00),
    "500088p.pdf": ("DoDI 5000.88", 0.75),
    "514301p.pdf": ("DoDD 5143.01", 0.75),
    "818001m.pdf": ("DoDM 8180.01", 0.75),
    "850001_2014.pdf": ("DoDI 8500.01", 0.75),
}


def expected_references() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    with CORPUS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["Document Name"].strip()
            out[name] = set(ast.literal_eval(row["References"] or "[]")) - {name}
    return out


@pytest.mark.parametrize("filename", sorted(FLOORS))
def test_extraction_meets_its_floor(filename):
    corpus_name, floor = FLOORS[filename]
    expected = expected_references()[corpus_name]

    found = set(pdf.extract_document(SAMPLES / filename).references)

    matched = len(expected & found) / len(expected)
    assert matched >= floor, (
        f"{corpus_name}: matched {matched:.0%}, floor is {floor:.0%}. "
        f"Missing: {sorted(expected - found)[:10]}"
    )
