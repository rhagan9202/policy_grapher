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
    """A closed enum: an adapter inventing 'WILL' must fail loudly, not silently."""
    with pytest.raises(ValidationError):
        ExtractedObligation(
            statement="x", modality="WILL", actor="a", deadline=None,
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
