import pytest
from canary.replay import diff


def test_an_unchanged_run_reports_nothing():
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    assert diff(baseline, dict(baseline)) == {"moved": [], "added": [], "removed": []}


def test_a_changed_modality_is_reported_as_moved():
    """The failure this exists for: a duty still found, its force downgraded."""
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    current = {"c1": [{"statement": "the director shall report", "modality": "SHOULD"}]}
    assert diff(baseline, current)["moved"][0]["chunk_id"] == "c1"


def test_a_chunk_that_became_a_rejection_is_reported():
    """Sprint 11's repetition loop turned a working chunk into a rejection, and
    nothing outside the gold set would have shown it."""
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    assert diff(baseline, {"c1": None})["moved"][0]["now"] is None


def test_a_chunk_absent_from_the_baseline_is_reported_as_added():
    assert diff({}, {"c1": [{"statement": "x", "modality": "SHALL"}]}) == {
        "moved": [],
        "added": ["c1"],
        "removed": [],
    }


def test_a_chunk_absent_from_the_current_run_is_reported_as_removed():
    baseline = {"c1": [{"statement": "the director shall report", "modality": "SHALL"}]}
    assert diff(baseline, {}) == {"moved": [], "added": [], "removed": ["c1"]}


@pytest.mark.integration
def test_the_canary_set_is_deterministic():
    from canary.replay import select_canary_chunks

    assert [c["chunk_id"] for c in select_canary_chunks(40)] == [
        c["chunk_id"] for c in select_canary_chunks(40)
    ]
