import httpx
import pytest
from canary.replay import TRANSPORT_ERROR, diff, record


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


# --- record() -------------------------------------------------------------
#
# `diff`'s own tests build baseline/current dicts by hand and never call
# `record`, so nothing above would notice `record` silently turning a
# rejection into an empty answer — the exact shape of the sprint-11 failure
# this whole feature exists to catch, just moved one function over.

_CHUNK = {"chunk_id": "c1", "text": "x", "section_path": [], "section_title": None}


class _RejectingExtractor:
    """Every call fails schema validation — the `ValueError` branch."""

    def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
        raise ValueError("model output did not match the obligation schema")


class _UnreachableExtractor:
    """The model server never answers — the `httpx.HTTPError` branch."""

    def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
        raise httpx.ReadTimeout("timed out")


def test_a_rejected_chunk_is_recorded_as_none_not_an_empty_list():
    """`None` means "the extractor answered and nothing survived validation";
    `[]` means "the extractor legitimately found no obligations". Collapsing
    the two loses the sprint-11 signal at its source."""
    assert record(_RejectingExtractor(), [_CHUNK]) == {"c1": None}


def test_a_transport_failure_is_recorded_distinguishably_from_a_rejection():
    """A dropped connection is a different failure mode from a model rejection
    (infra flake vs. the model actively refusing the passage) and from a
    legitimate empty answer, so it gets its own sentinel rather than being
    folded into either."""
    result = record(_UnreachableExtractor(), [_CHUNK])
    assert result == {"c1": TRANSPORT_ERROR}
    assert result["c1"] is not None
    assert result["c1"] != []


# --- select_canary_chunks() ------------------------------------------------
#
# Reads real PDFs from data/samples, so these are slower than the rest of this
# file (~7.5s vs ~0.01s) but need no external service — `slow`, not
# `integration` (that marker is documented as "requires live Neo4j and Redis
# containers", neither of which this touches).


@pytest.mark.slow
def test_the_canary_set_is_deterministic():
    from canary.replay import select_canary_chunks

    first = select_canary_chunks(40)
    second = select_canary_chunks(40)
    # `== []` on both sides would satisfy a bare equality check with the
    # samples directory renamed, the glob broken, or the chunker returning
    # nothing — this fails that case outright rather than trusting equality
    # alone to notice an empty result.
    assert len(first) == 40
    assert [c["chunk_id"] for c in first] == [c["chunk_id"] for c in second]


@pytest.mark.slow
def test_the_canary_set_spans_each_documents_body():
    """Round-robin over raw chunk index alone reaches only the first six
    chunks of every document at N=40 over 7 documents — cover pages and short
    stubs, never a document's body, never RESPONSIBILITIES, the exact section
    the last three regressions happened in. This fails if selection regresses
    to that shape."""
    from canary.replay import SAMPLES, select_canary_chunks

    from policy_grapher.chunking import chunk_pages
    from policy_grapher.sources import pdf

    selected_ids = {c["chunk_id"] for c in select_canary_chunks(40)}

    reached_past_the_opening_chunks = False
    for path in sorted(SAMPLES.glob("*.pdf")):
        document = pdf.extract_document(path)
        ids = [
            chunk.chunk_id
            for chunk in chunk_pages(document.pages, version_id=path.stem)
        ]
        positions = [
            index for index, chunk_id in enumerate(ids) if chunk_id in selected_ids
        ]
        assert positions, f"{path.name} contributed no chunks to the canary set"
        if max(positions) > 5:
            reached_past_the_opening_chunks = True

    assert reached_past_the_opening_chunks, (
        "every document's sample stayed within its first six chunks — "
        "the canary set is blind to every document's body"
    )
