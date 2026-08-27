"""The scorer's own tests. A ratchet is only as trustworthy as its arithmetic."""

import pytest

from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.extraction.scoring import micro_average, score


def _o(statement: str, modality: Modality = Modality.SHALL) -> ExtractedObligation:
    return ExtractedObligation(
        statement=statement,
        modality=modality,
        actor=None,
        deadline=None,
        conditions=None,
        confidence=0.9,
    )


GOLD = [_o("The Director shall notify."), _o("The PM shall report.")]


def test_a_perfect_answer_scores_one_across_the_board():
    result = score(list(GOLD), GOLD)
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["modality_accuracy"] == 1.0


def test_a_miss_costs_recall_but_not_precision():
    result = score([GOLD[0]], GOLD)
    assert result["recall"] == pytest.approx(0.5)
    assert result["precision"] == 1.0


def test_a_false_positive_costs_precision_but_not_recall():
    result = score([*GOLD, _o("The Director shall invent a duty.")], GOLD)
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == 1.0


def test_the_right_statement_with_the_wrong_modality_costs_only_modality():
    """The failure an aggregate F1 hides: the duty was found, its force downgraded."""
    # A sentence carrying both words, because the schema now requires a statement
    # to contain the modality it is labelled with — a model can no longer call a
    # sentence SHOULD when the word is nowhere in it. Mislabelling is still real,
    # and this is the shape it now takes.
    both = "The Director shall notify and should consider delegating."
    gold = [_o(both, Modality.SHALL), GOLD[1]]
    downgraded = _o(both, Modality.SHOULD)

    result = score([downgraded, GOLD[1]], gold)

    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["modality_accuracy"] == pytest.approx(0.5)


def test_matching_ignores_whitespace_and_case():
    """Compared the way identity is compared, so a match here means a stable id."""
    reflowed = _o("the  DIRECTOR   shall\nnotify.")
    assert score([reflowed], [GOLD[0]])["recall"] == 1.0


def test_inventing_an_obligation_where_there_is_none_scores_zero_precision():
    """The definitional fixture's whole purpose."""
    assert score([_o("A manufactured duty shall be reported.")], [])["precision"] == 0.0


def test_correctly_finding_nothing_is_a_perfect_answer():
    result = score([], [])
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0


def test_finding_nothing_when_there_was_something_scores_zero_recall():
    assert score([], GOLD)["recall"] == 0.0


def test_modality_accuracy_is_vacuous_when_nothing_matched():
    """It answers 'when we found the duty, did we get its force right?'. With no
    matches there is no answer, and the recall floor is what catches that."""
    assert score([], GOLD)["modality_accuracy"] == 1.0


def test_a_repeated_statement_is_counted_as_the_duplicate_it_is():
    """Emitting the same duty twice is one find and one false positive."""
    result = score([GOLD[0], GOLD[0]], GOLD)
    assert result["precision"] == 1.0
    assert result["recall"] == pytest.approx(0.5)
    assert result["matched"] == 2


def test_the_counts_support_micro_averaging_across_fixtures():
    """Averaging per-fixture rates would let the empty-gold fixture contribute a
    vacuous 1.0 recall. The ratchet pools counts instead, so it needs them."""
    result = score([GOLD[0], _o("An invented duty shall exist.")], GOLD)
    assert result["matched"] == 1
    assert result["predicted"] == 2
    assert result["gold"] == 2
    assert result["modality_correct"] == 1
    assert result["modality_considered"] == 1


def test_pooling_does_not_let_an_empty_fixture_inflate_recall():
    """Averaging the rates would score this extractor 0.5 recall — it found
    nothing anywhere, and the empty fixture's vacuous 1.0 would carry it.
    Pooling the counts scores it 0.0, which is the truth."""
    found_nothing = score([], GOLD)
    correct_nothing = score([], [])

    assert (found_nothing["recall"] + correct_nothing["recall"]) / 2 == pytest.approx(0.5)
    assert micro_average([found_nothing, correct_nothing])["recall"] == 0.0
