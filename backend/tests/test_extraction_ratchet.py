"""Extraction quality as numbers that fail the build when they regress.

Two ratchets per fixture, guarding opposite failure modes:

**Floors** — the fraction of a document's real references we must find. Measured when
the parser was written, rounded down to the nearest 5%. They may only be raised.

**Ceilings** — how many references we may invent that the corpus does not list. Every
spurious reference becomes an `:External` node with no basis in the corpus, so recall
alone is a half-guard: a change that doubled the invented edges would pass every floor
while quietly corrupting the graph. Ceilings are the measured counts exactly, so they
may only be lowered.

Lowering a floor or raising a ceiling needs a reason in the commit message.
"""

import ast
import csv
from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
CORPUS = SAMPLES / "dod_policy_references_08122026.csv"

# fixture -> (corpus name, minimum fraction found, maximum invented)
RATCHETS = {
    "500001p.pdf": ("DoDD 5000.01", 1.00, 0),
    "500088p.pdf": ("DoDI 5000.88", 0.75, 3),
    "514301p.pdf": ("DoDD 5143.01", 0.75, 13),
    "818001m.pdf": ("DoDM 8180.01", 0.75, 4),
    "850001_2014.pdf": ("DoDI 8500.01", 0.75, 22),
}


def expected_references() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    with CORPUS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["Document Name"].strip()
            out[name] = set(ast.literal_eval(row["References"] or "[]")) - {name}
    return out


@pytest.mark.parametrize("filename", sorted(RATCHETS))
def test_extraction_meets_its_floor(filename):
    corpus_name, floor, _ = RATCHETS[filename]
    expected = expected_references()[corpus_name]

    found = set(pdf.extract_document(SAMPLES / filename).references)

    matched = len(expected & found) / len(expected)
    assert matched >= floor, (
        f"{corpus_name}: matched {matched:.0%}, floor is {floor:.0%}. "
        f"Missing: {sorted(expected - found)[:10]}"
    )


@pytest.mark.parametrize("filename", sorted(RATCHETS))
def test_extraction_stays_under_its_spurious_ceiling(filename):
    corpus_name, _, ceiling = RATCHETS[filename]
    expected = expected_references()[corpus_name]

    found = set(pdf.extract_document(SAMPLES / filename).references)

    spurious = found - expected
    assert len(spurious) <= ceiling, (
        f"{corpus_name}: invented {len(spurious)} references, ceiling is {ceiling}. "
        f"Each becomes an :External node with no corpus basis. "
        f"Invented: {sorted(spurious)[:10]}"
    )
