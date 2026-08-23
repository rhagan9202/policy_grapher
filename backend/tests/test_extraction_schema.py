import pytest
from pydantic import ValidationError

from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)


def test_a_well_formed_obligation_validates():
    o = ExtractedObligation(
        statement="The Director shall notify the Comptroller within 24 hours.",
        modality=Modality.SHALL,
        actor="The Director",
        deadline="24 hours",
        conditions=None,
        confidence=0.9,
    )
    assert o.modality is Modality.SHALL


def test_an_unknown_modality_is_rejected():
    """A closed enum: an adapter inventing a modality must fail loudly.

    The example used to be 'WILL', which ADR-025 admitted to the set once the
    corpus was counted — `will` outnumbers `shall` 458 to 93. The rule this test
    asserts did not change; only which words are in the set. 'OUGHT' stands in
    because no DoD issuance imposes a duty with it.
    """
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality="OUGHT", actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_confidence_outside_zero_to_one_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=1.4,
        )


def test_an_empty_statement_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="   ", modality=Modality.MAY, actor="a", deadline=None,
            conditions=None, confidence=0.5,
        )


def test_identity_is_stable_across_runs():
    args = ("v", ["3", "3.2"], "The Director shall notify the Comptroller.")
    assert obligation_id(*args) == obligation_id(*args)


def test_identity_ignores_whitespace_and_case_in_the_statement():
    """Re-extraction must not orphan a human decision over a reflowed line."""
    a = obligation_id("v", ["3.2"], "The Director shall notify.")
    b = obligation_id("v", ["3.2"], "the  director   SHALL notify.")
    assert a == b


def test_identity_distinguishes_sections():
    a = obligation_id("v", ["3.2"], "Same words.")
    b = obligation_id("v", ["4.1"], "Same words.")
    assert a != b


def test_identity_distinguishes_versions():
    a = obligation_id("v1", ["3.2"], "Same words.")
    b = obligation_id("v2", ["3.2"], "Same words.")
    assert a != b


# --- WILL, and what makes an obligation binding (STORY-055, ADR-025) -----------


def test_will_is_a_modality_this_corpus_actually_uses():
    """`shall` 93 against `will` 458 across the seven samples, and it is
    generational rather than incidental: the 2003 edition of DoDD 5000.01 uses
    `shall` 92 times and `must` never, while its 2020 re-issue uses `shall` zero
    times and `will` 44. An extractor obeying the old enum could only report a
    minority of a modern issuance's duties."""
    assert Modality("WILL") is Modality.WILL


def test_a_will_obligation_is_binding():
    """DoD's plain-language drafting replaced the directive `shall` with `will`.
    It is a duty, not an expectation."""
    assert ExtractedObligation(
        statement="The DoD Components will report annually.",
        modality=Modality.WILL,
        actor="DoD Components",
        deadline="annually",
        conditions=None,
        confidence=0.9,
    ).is_binding


def test_shall_and_must_stay_binding():
    for modality in (Modality.SHALL, Modality.MUST):
        assert ExtractedObligation(
            statement="The Director shall notify.",
            modality=modality,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        ).is_binding


def test_should_and_may_are_not_binding():
    """The distinction the closed enum exists to protect. A binding duty read as
    advice is the silent downgrade `schema.py` refuses to allow."""
    for modality in (Modality.SHOULD, Modality.MAY):
        assert not ExtractedObligation(
            statement="The Director should consider notifying.",
            modality=modality,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        ).is_binding


def test_bindingness_is_asked_of_the_obligation_not_pattern_matched():
    """Every member has an answer, so no consumer has to keep its own list of
    which names count — the way a consumer written before WILL existed would."""
    for modality in Modality:
        obligation = ExtractedObligation(
            statement="A duty.",
            modality=modality,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.5,
        )
        assert isinstance(obligation.is_binding, bool)
