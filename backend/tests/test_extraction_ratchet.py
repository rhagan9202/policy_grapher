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
import json
from pathlib import Path

import pytest

from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
CORPUS = SAMPLES / "dod_policy_references_08122026.csv"

# What each edition of a multi-edition document actually cites, transcribed by hand
# from its own references section (STORY-073). The corpus CSV cannot answer this: it
# holds one row per document *name*, describing whichever edition was current when it
# was written.
EDITION_REFERENCES = json.loads(
    (Path(__file__).parent / "fixtures" / "editions" / "expected_references.json")
    .read_text(encoding="utf-8")
)

# fixture -> (expected-set key, minimum fraction found, maximum invented)
#
# Every PDF in `data/samples` appears here. Two of them are editions of DoDD 5000.01
# other than the one the corpus CSV describes, and until STORY-073 they had no floor
# at all — because scoring them against that row measured how much two editions
# disagree rather than how well extraction works. The 2003 edition read as 7% recall
# with 11 "inventions", every one of which was a genuine citation.
#
# They now score against their own transcribed reference lists, and the numbers are
# real measurements of extraction: 12 of 14 and 16 of 17, nothing invented. What each
# misses is worth knowing — the FAR and a bare `Section 2222, title 10` on the 2003
# cover, and a quoted strategy title with no issuance number on the 2020 one. Those
# are shapes the parser does not reach, which is what a floor is for.
RATCHETS = {
    "500001p.pdf": ("DoDD 5000.01", 1.00, 0),
    "500001p_2003.pdf": ("500001p_2003.pdf", 0.857, 0),
    "500001p_2020.pdf": ("500001p_2020.pdf", 0.941, 0),
    "500088p.pdf": ("DoDI 5000.88", 0.75, 3),
    "514301p.pdf": ("DoDD 5143.01", 0.75, 13),
    "818001m.pdf": ("DoDM 8180.01", 0.75, 4),
    "850001_2014.pdf": ("DoDI 8500.01", 0.75, 22),
}


def expected_references() -> dict[str, set[str]]:
    """Every expected set, from both homes, keyed the way `RATCHETS` names them.

    A document name resolves to the corpus CSV's row for it; a *filename* resolves
    to that edition's own transcribed list. The two are different subjects, which
    is why they live apart (STORY-073): the CSV says what a document cites, and
    the edition file says what one edition cites.
    """
    out: dict[str, set[str]] = {}
    with CORPUS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            name = row["Document Name"].strip()
            out[name] = set(ast.literal_eval(row["References"] or "[]")) - {name}

    for filename, entry in EDITION_REFERENCES.items():
        if not filename.startswith("_"):
            out[filename] = set(entry["references"])
    return out


def test_every_sample_pdf_is_ratcheted():
    """A fixture added and left unguarded is a fixture nobody is measuring, and
    that is how two editions of DoDD 5000.01 went unratcheted for four sprints.

    No exclusion list: if one is ever needed it belongs here with its reason, and
    the absence of one is the claim that none is needed.
    """
    on_disk = {path.name for path in SAMPLES.glob("*.pdf")}

    assert on_disk == set(RATCHETS), (
        f"unratcheted: {sorted(on_disk - set(RATCHETS))}; "
        f"ratcheted but missing from data/samples: {sorted(set(RATCHETS) - on_disk)}"
    )


def test_every_expected_set_a_ratchet_names_exists():
    """A ratchet naming a key nothing provides would raise a KeyError mid-run
    rather than fail with a reason."""
    available = expected_references()
    for filename, (key, _floor, _ceiling) in RATCHETS.items():
        assert key in available, f"{filename} scores against {key!r}, which has no expected set"
        assert available[key], f"{key!r} has an empty expected set, so its floor cannot fail"


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
