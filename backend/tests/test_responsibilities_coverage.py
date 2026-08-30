"""STORY-105: a floor under how much of a responsibilities section is read.

The extraction ratchet floors precision, recall and modality accuracy against
gold *passages*. It is structurally blind to coverage: a change that stops
reading four role sections entirely leaves every gold fixture passing, because
no fixture comes from those sections.

That is not hypothetical. Sprint 10 shipped with the gate green while DoDD
5000.01 (2020) was read at 19 of 40 lettered items, and four role sections —
CMO, DoD CIO, DOT&E and CJCS — yielded nothing at all. The gap was found by
hand-counting the document at sprint 11 planning, two sprints after the number
that hid it was first published.

Same shape as STORY-073's reference floor, for the same reason: a per-passage
score says nothing about how much of the document was reached.
"""

import re
from pathlib import Path

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor
from policy_grapher.sources.pdf import pages_of

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

# Counted by hand from the chunks the chunker produces, at sprint 11 planning,
# because extraction operates on chunks and a count taken from raw page text
# segments differently — the first count of this document disagreed with itself
# on three paragraphs while agreeing on the total.
#
# Keyed by the paragraph each role section opens. `(none)` is the items that sit
# directly under SECTION 2 rather than under a numbered role heading.
EXPECTED_ROLE_ITEMS = {
    "500001p_2020.pdf": {
        "2.1": 5,   # USD(A&S)
        "2.2": 6,   # USD(R&E)
        "2.3": 4,   # USD(I&S)
        "2.4": 0,   # USD(P&R) — prose, no lettered items
        "2.5": 2,   # CMO
        "2.6": 6,   # DoD CIO
        "2.7": 4,   # DOT&E
        "2.8": 4,   # DCAPE
        "2.9": 2,   # DoD Component Heads
        "2.10": 3,  # CJCS
        "(none)": 4,
    }
}

LETTERED_ITEM = re.compile(r"^[a-z]\.\s+[A-Z]")

# Measured 2026-08-30 (sprint 11), after PROMPT_VERSION 4 taught the two role
# heading forms the prompt had never described: **34 of 40, 0.850**, against 19 of
# 40 before it. Paragraphs 2.3, 2.6 and 2.7 went from 1, 0 and 0 to complete.
#
# Deliberately NOT set to the observed 0.850, for the reason recorded beside
# `modality_accuracy` in the extraction ratchet: over 40 items one item is 0.025,
# so a floor at the observation fires the moment a single item moves, and a floor
# that fires on one differing answer teaches people to ignore it. 0.80 tolerates
# two and catches three.
#
# Honest about its own precision: this counts ASSIGNED obligations per paragraph
# against lettered items per paragraph, and the extractor over-reads some
# paragraphs while under-reading others — 2.1 returned 6 against 5 expected while
# 2.5 returned 0 against 2. The ratio is a coverage signal, not a per-item match,
# and a paragraph reading zero is the failure it exists to catch.
#
# One measurement, not three. The extraction gate was shown deterministic across
# six runs in two processes on this build, so a second coverage run was judged
# redundant rather than skipped — if that proves wrong this floor is where it
# shows up first.
COVERAGE_FLOOR = 0.80


def _paragraph(chunk) -> str:
    return chunk.section_path[-1] if len(chunk.section_path) > 1 else "(none)"


def _responsibilities_chunks(filename: str):
    return [
        c
        for c in chunk_pages(pages_of(SAMPLES / filename), version_id="coverage")
        if c.section_title and "RESPONSIBILIT" in c.section_title
    ]


@pytest.mark.integration
@pytest.mark.parametrize("filename", sorted(EXPECTED_ROLE_ITEMS))
def test_the_hand_count_still_matches_the_document(filename):
    """The denominator is checked before it is trusted.

    This is the cheap half and it needs no model. The count above was wrong once
    already — published, quoted in two sprint reviews and two velocity rows, and
    used as a denominator by two sprints before anybody counted the document.
    """
    counted = {}
    for chunk in _responsibilities_chunks(filename):
        n = sum(1 for line in chunk.text.splitlines() if LETTERED_ITEM.match(line.strip()))
        counted[_paragraph(chunk)] = counted.get(_paragraph(chunk), 0) + n

    assert counted == EXPECTED_ROLE_ITEMS[filename], (
        f"the hand count for {filename} no longer matches the document. Either the "
        f"chunker changed what it produces, or the count was wrong. Counted "
        f"{counted}, expected {EXPECTED_ROLE_ITEMS[filename]}."
    )


@pytest.mark.integration
@pytest.mark.parametrize("filename", sorted(EXPECTED_ROLE_ITEMS))
def test_enough_of_the_responsibilities_section_is_read(filename):
    """The floor, and the expensive half.

    Reports which role sections yielded nothing, because that is the failure that
    matters: an aggregate proportion can stay respectable while an entire office's
    duties go missing, which is exactly how 19 of 40 passed unnoticed.
    """
    settings = Settings()
    extractor = build_extractor(settings)
    if settings.extractor_adapter == "null":
        pytest.skip(
            "THE COVERAGE FLOOR DID NOT RUN: the null adapter extracts nothing, so "
            "this would measure zero against any floor. A green suite does not mean "
            "coverage held — it means nothing checked."
        )

    expected = EXPECTED_ROLE_ITEMS[filename]
    found: dict[str, int] = {}
    for chunk in _responsibilities_chunks(filename):
        try:
            obligations = extractor.extract(
                chunk.text,
                section_path=chunk.section_path,
                section_title=chunk.section_title,
            )
        except ValueError:
            # What production does with a chunk whose output fails the schema
            # (ADR-023, ADR-030): the chunk is rejected and the run continues. A
            # rejected chunk contributes nothing, which is precisely the failure
            # this floor exists to price in rather than crash on.
            obligations = []
        assigned = sum(1 for o in obligations if o.modality == "ASSIGNED")
        found[_paragraph(chunk)] = found.get(_paragraph(chunk), 0) + assigned

    total_expected = sum(expected.values())
    total_found = sum(found.values())
    coverage = total_found / total_expected

    dark = sorted(p for p, n in expected.items() if n and not found.get(p))
    assert coverage >= COVERAGE_FLOOR, (
        f"{filename} read {total_found} of {total_expected} lettered items "
        f"({coverage:.2f} against a floor of {COVERAGE_FLOOR:.2f}). Role sections "
        f"that yielded nothing: {dark or 'none'}. Fix the extractor — do not lower "
        f"the floor."
    )
