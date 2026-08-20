"""Scoring an extractor against a hand-labelled gold set.

Three numbers, pinned separately rather than folded into one. An aggregate F1
hides the failure that matters most here: a SHALL read as a SHOULD, which finds
the duty and silently downgrades it from binding to advisory. So modality gets
its own leg, and its own floor.

Matching is on `schema.normalize(statement)` — the same form obligation identity
is computed over. That is a deliberately hard bar: a paraphrase does not match.
It has to be, because a paraphrase produces a different obligation_id, and an id
that moves on every run orphans the human decisions Phase 4 attaches to it. An
extractor that cannot quote the passage cannot anchor to it either.
"""

from policy_grapher.extraction.schema import ExtractedObligation, normalize


def score(
    predicted: list[ExtractedObligation], gold: list[ExtractedObligation]
) -> dict:
    """Precision, recall and modality accuracy for one passage.

    Raw counts come back alongside the rates so a caller can micro-average over
    several passages. Averaging the rates instead would let a fixture whose
    correct answer is empty contribute a vacuous recall of 1.0 and quietly lift
    the score of an extractor that found nothing anywhere.
    """
    gold_by_key = {normalize(g.statement): g for g in gold}
    matched = [p for p in predicted if normalize(p.statement) in gold_by_key]
    found_keys = {normalize(p.statement) for p in predicted} & gold_by_key.keys()

    modality_correct = sum(
        1
        for p in matched
        if p.modality is gold_by_key[normalize(p.statement)].modality
    )

    return {
        # An extractor that says nothing has said nothing wrong.
        "precision": len(matched) / len(predicted) if predicted else 1.0,
        "recall": len(found_keys) / len(gold_by_key) if gold_by_key else 1.0,
        # Vacuous with no matches. The recall floor is what catches that case;
        # this leg only answers "having found the duty, did we get its force right?"
        "modality_accuracy": modality_correct / len(matched) if matched else 1.0,
        "matched": len(matched),
        "predicted": len(predicted),
        "gold": len(gold_by_key),
        "found": len(found_keys),
        "modality_correct": modality_correct,
        "modality_considered": len(matched),
    }


def micro_average(scores: list[dict]) -> dict:
    """Pool counts across passages, then take the rates once."""
    total = {
        field: sum(s[field] for s in scores)
        for field in ("matched", "predicted", "gold", "found", "modality_correct", "modality_considered")
    }
    return {
        "precision": total["matched"] / total["predicted"] if total["predicted"] else 1.0,
        "recall": total["found"] / total["gold"] if total["gold"] else 1.0,
        "modality_accuracy": (
            total["modality_correct"] / total["modality_considered"]
            if total["modality_considered"]
            else 1.0
        ),
        **total,
    }
