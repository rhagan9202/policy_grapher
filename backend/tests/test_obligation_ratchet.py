"""The swap gate: extraction quality as numbers that fail the build when they regress.

`test_extraction_ratchet.py` pins the deterministic *citation* parser. This pins
the *obligation* extractor, which is a model behind a port — so the numbers are
per adapter, and a provider swap is legal only when the new adapter clears its
floors. That is what makes "swappable" a tested property rather than a hope.

Floors ratchet **up**. Raise one when a run beats it; never lower one to turn a
red suite green. A lowered floor needs a reason in the commit message.

`precision`, `recall` and `modality_accuracy` are pinned separately on purpose.
A SHALL read as a SHOULD finds the duty and downgrades it from binding to
advisory — an aggregate score absorbs that, and this is a compliance tool.
"""

import json
from pathlib import Path

import httpx
import pytest

from policy_grapher.config import Settings
from policy_grapher.extraction import build_extractor
from policy_grapher.extraction.schema import ExtractedObligation, normalize
from policy_grapher.extraction.scoring import micro_average, score

GOLD = Path(__file__).parent / "fixtures" / "gold"

# Model provenance is a procurement constraint here, not a preference. This corpus
# is heading toward controlled unclassified information, and the default extraction
# model must be published by a US organisation (ADR-020). Adding to this set is a
# supply-chain decision and should be argued for in review.
US_ORIGIN_MODELS = frozenset(
    {
        "llama3.1:8b",  # Meta
        "llama3.2:3b",  # Meta
        "granite3.3:8b",  # IBM
        "phi4:14b",  # Microsoft
    }
)

# Per adapter. The local model is for iteration speed; a hosted adapter must
# clear the production bar before it is promoted.
#
# **Measured 2026-08-21** against llama3.1:8b on CPU, temperature 0 — the first
# time this gate has ever run against a real model rather than skipping (it had
# no model server to reach until the `models` compose profile existed). Observed,
# micro-averaged over the three gold fixtures: precision 0.600, recall 0.500,
# modality accuracy 1.000, from matched=3, predicted=5, gold=6.
#
# Precision and recall are recorded exactly as observed, which happens to equal
# the estimates they replace. **They pass by zero margin**, and with six gold
# obligations a single different answer moves recall by 0.167 — so a red build
# here means "the answer changed", not necessarily "the model got worse".
# Widening the gold set is the prerequisite for treating this as a real gate.
#
# Modality is deliberately NOT raised to the observed 1.000: it was computed over
# three matched pairs, where one error would read as 0.667. A floor that fires on
# noise rather than on regression teaches people to ignore it.
FLOORS = {
    "null": {"precision": 0.0, "recall": 0.0, "modality_accuracy": 0.0},
    "local:llama3.1:8b": {"precision": 0.60, "recall": 0.50, "modality_accuracy": 0.85},
}


def _gold_cases() -> list[tuple[str, dict]]:
    cases = [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(GOLD.glob("*.json"))
    ]
    assert cases, f"no gold fixtures in {GOLD}"
    return cases


def _model_is_reachable(settings: Settings) -> bool:
    try:
        httpx.get(f"{settings.extractor_base_url.rstrip('/')}/api/tags", timeout=2.0)
    except httpx.HTTPError:
        return False
    return True


@pytest.mark.parametrize("name", [name for name, _ in _gold_cases()])
def test_the_gold_set_is_well_formed(name):
    """Every labelled obligation validates, and quotes its passage verbatim.

    Matching is on the normalized statement, so a gold statement that is a
    paraphrase of its passage rather than a quotation makes the recall floor
    unreachable by construction — and the tempting fix for an unreachable floor
    is to lower it, which is exactly what a ratchet must never allow.
    """
    case = dict(_gold_cases())[name]
    passage = normalize(case["chunk_text"])

    for raw in case["obligations"]:
        obligation = ExtractedObligation.model_validate(raw)
        assert normalize(obligation.statement) in passage, (
            f"{name}: gold statement is not a verbatim quotation of the passage: "
            f"{obligation.statement!r}"
        )


def test_the_gold_set_covers_the_cases_that_discriminate():
    """Three shapes, each catching a failure the others cannot: a passage dense in
    duties (recall), a passage with none (precision), and one mixing modalities
    against 'may' used as prediction rather than permission (modality)."""
    cases = dict(_gold_cases())
    counts = sorted(len(c["obligations"]) for c in cases.values())
    modalities = {
        o["modality"] for c in cases.values() for o in c["obligations"]
    }

    assert len(cases) >= 3
    assert counts[0] == 0, "no fixture whose correct answer is empty"
    assert counts[-1] >= 3, "no fixture dense enough to measure recall"
    assert len(modalities) >= 2, "no fixture mixing modalities"


class _InventingExtractor:
    """Reports a duty in every passage, including the one that has none."""

    adapter_id = "inventing"

    def extract(self, chunk_text, *, section_path):
        return [
            ExtractedObligation(
                statement="The Component shall comply with this issuance.",
                modality="SHALL",
                actor="The Component",
                deadline=None,
                conditions=None,
                confidence=0.9,
            )
        ]


def test_the_gate_has_teeth():
    """An extractor that manufactures duties must fail the floors a real adapter
    has to clear. Without this the gate could be vacuously green and nobody would
    know until a bad adapter shipped."""
    scores = [
        score(
            _InventingExtractor().extract(
                case["chunk_text"], section_path=case["section_path"]
            ),
            [ExtractedObligation.model_validate(o) for o in case["obligations"]],
        )
        for _, case in _gold_cases()
    ]
    overall = micro_average(scores)
    floors = FLOORS["local:llama3.1:8b"]

    assert overall["precision"] < floors["precision"]
    assert overall["recall"] < floors["recall"]


@pytest.mark.integration
def test_the_configured_extractor_clears_its_floors():
    settings = Settings()
    extractor = build_extractor(settings)
    floors = FLOORS.get(extractor.adapter_id)

    if floors is None:
        pytest.skip(
            f"THE EXTRACTION GATE DID NOT RUN: no floors are recorded for adapter "
            f"{extractor.adapter_id!r}. Record them in FLOORS before using it."
        )
    if settings.extractor_adapter != "null" and not _model_is_reachable(settings):
        pytest.skip(
            f"THE EXTRACTION GATE DID NOT RUN: no model server answered at "
            f"{settings.extractor_base_url}. A green suite does not mean adapter "
            f"{extractor.adapter_id!r} passed its floors — it means nothing checked."
        )

    scores = []
    for name, case in _gold_cases():
        predicted = extractor.extract(
            case["chunk_text"], section_path=case["section_path"]
        )
        gold = [ExtractedObligation.model_validate(o) for o in case["obligations"]]
        scores.append(score(predicted, gold))

    overall = micro_average(scores)
    below = {
        leg: (overall[leg], floor)
        for leg, floor in floors.items()
        if overall[leg] < floor
    }
    assert not below, (
        f"{extractor.adapter_id} scored below its floor: "
        + "; ".join(f"{leg} {got:.2f} < {floor:.2f}" for leg, (got, floor) in below.items())
        + f". Full scores: {overall}. Fix the extractor — do not lower the floor."
    )


def test_the_shipped_model_has_recorded_floors():
    """The gate must be able to gate what the stack actually runs.

    `FLOORS` is keyed by `adapter_id`, which embeds the model name, so a default
    model with no entry makes the ratchet skip silently — it reports "no floors
    recorded" and a green suite means nothing was checked. That is exactly the
    state this project was in while `FLOORS` named a model the settings did not.
    """
    settings = Settings(_env_file=None, extractor_adapter="local")
    adapter_id = build_extractor(settings).adapter_id

    assert adapter_id in FLOORS, (
        f"the configured default model has no recorded floors: {adapter_id!r} is "
        f"not in {sorted(FLOORS)}. The gate would skip rather than gate."
    )


def test_the_default_extraction_model_is_us_origin():
    """ADR-020. Qwen (Alibaba) and DeepSeek are capable and are not eligible here;
    the constraint is where the weights come from, not how they score."""
    assert Settings(_env_file=None).extractor_model in US_ORIGIN_MODELS, (
        f"{Settings(_env_file=None).extractor_model!r} is not in the US-origin set "
        f"{sorted(US_ORIGIN_MODELS)}"
    )
