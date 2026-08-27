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
from policy_grapher.extraction.schema import ExtractedObligation, Modality, normalize
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

# The same constraint, applied to the other kind of weights this system loads.
# ADR-020 governed extraction only and said so, naming the embedding default as "a
# related gap this ADR does not close" and "the first thing to check if this
# constraint is ever audited". STORY-060 is that audit. See ADR-024.
US_ORIGIN_EMBEDDING_MODELS = frozenset(
    {
        "Snowflake/snowflake-arctic-embed-s",  # Snowflake Inc.
        "Snowflake/snowflake-arctic-embed-m",  # Snowflake Inc.
        "nomic-ai/nomic-embed-text-v1.5",  # Nomic AI
    }
)

# Per adapter. The local model is for iteration speed; a hosted adapter must
# clear the production bar before it is promoted.
#
# **Measured 2026-08-21** against llama3.1:8b on CPU, temperature 0 — the first
# time this gate has ever run against a real model rather than skipping (it had
# no model server to reach until the `models` compose profile existed). Observed,
# Re-measured 2026-08-26 (STORY-084) against the five-fixture, thirteen-obligation
# gold set, with a live llama3.1:8b at temperature 0. Observed, and identical on
# three consecutive runs:
#
#     precision 0.625   recall 0.769   modality 1.000   matched 10 of 13
#
# Recorded exactly as observed, which this file has always done. The previous
# floors were measured over three fixtures and six obligations and their comment
# said the widened gold set was "the prerequisite for treating this as a real
# gate"; that prerequisite is now met, and one differing answer moves recall by
# 0.077 rather than 0.167.
#
# **Getting here meant fixing the extractor, not the floor.** Run against the
# widened gold set the model first scored precision 0.294 / recall 0.385, well
# under the floors then recorded — the gate's own message says "Fix the extractor
# — do not lower the floor", and lowering them would have rebuilt the vacuous gate
# `FLOORS["null"]` had just been removed for. The failure was real: llama3.1:8b
# was writing statements that began at the verb, dropping the subject into
# `actor`, so "PMs shall manage programs..." came back as "manage programs...".
# `scoring.py` matches on the same normalised form `obligation_id` is hashed from,
# so those are different obligations and the human decisions attached to the old
# id are orphaned. PROMPT_VERSION 2 makes the quoting rule explicit and names the
# three shapes that look like duties and carry no modal verb.
#
# modality is deliberately NOT raised to the observed 1.000. Over ten matched
# pairs a single error reads as 0.900, and a floor that fires on one different
# answer teaches people to ignore it. 0.85 tolerates one and catches two.
FLOORS = {
    "local:llama3.1:8b": {"precision": 0.625, "recall": 0.769, "modality_accuracy": 0.85},
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


def test_the_gold_set_covers_every_modality_the_schema_allows():
    """STORY-084 AC5, and the same shape as
    `test_every_modality_the_schema_allows_has_a_weight` in `test_triage.py`.

    `modality_accuracy` is scored over matched pairs, so a modality with no gold
    example is a modality the floor cannot measure: an adapter could get MAY
    wrong every time and the number would not move. The enum is the definition of
    what has to be covered, so comparing against it means adding a modality later
    fails here until the gold set catches up — which is exactly what happened when
    ADR-025 added WILL, and what the weight-table test caught within a minute.
    """
    labelled = {
        obligation["modality"]
        for case in dict(_gold_cases()).values()
        for obligation in case["obligations"]
    }

    missing = {m.value for m in Modality} - labelled
    assert not missing, (
        f"the gold set labels no {sorted(missing)} obligation, so the ratchet's "
        f"modality_accuracy cannot measure it. Add a fixture quoting one."
    )


class _InventingExtractor:
    """Reports a duty in every passage, including the one that has none."""

    adapter_id = "inventing"

    def extract(self, chunk_text, *, section_path, on_drop=None):
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
        try:
            predicted = extractor.extract(
                case["chunk_text"], section_path=case["section_path"]
            )
        except ValueError:
            # What production does with a chunk whose output fails the schema
            # (ADR-023): reject the chunk, keep the run. Letting it raise here
            # would end the gate with an error instead of a score, which reports
            # "the suite broke" for what is really "the model produced invalid
            # output" — a quality failure the recall floor should price in, not a
            # crash. Measured 2026-08-26: llama3.1:8b does this on the
            # definitional fixture, returning a null modality for a scope
            # sentence.
            predicted = []
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


def test_the_default_embedding_model_is_us_origin():
    """ADR-024, extending ADR-020 to the weights that produce vectors.

    `all-MiniLM-L6-v2` is published by UKP Lab at TU Darmstadt and was the default
    until STORY-060's audit. ADR-020 named it as the gap to check first.
    """
    model = Settings(_env_file=None).embedder_model
    assert model in US_ORIGIN_EMBEDDING_MODELS, (
        f"{model!r} is not in the US-origin embedding set "
        f"{sorted(US_ORIGIN_EMBEDDING_MODELS)}. Changing it after a corpus is "
        "embedded means re-embedding that corpus (ADR-016), so this is cheap to get "
        "right and expensive to get wrong."
    )


def test_compose_does_not_override_the_default_with_an_ineligible_model():
    """The gap the test above cannot see, found by sprint 4's walkthrough.

    `Settings` reads the environment, and compose supplies one. Asserting on
    `Settings(_env_file=None)` therefore checks what a *developer's shell* resolves,
    not what a *container* resolves — and those disagreed: `config.py` defaulted to
    llama3.1:8b while docker-compose.yml passed `EXTRACTOR_MODEL:
    ${EXTRACTOR_MODEL:-qwen3:8b}` to both backend and worker. Any machine whose .env
    predated that key ran the exact model ADR-020 forbids, while the test above
    passed on every developer's host, because `EXTRACTOR_MODEL` is unset there.

    ADR-020 says the constraint is enforced by a test rather than a convention. It
    was only enforced for one of the two places the value comes from.
    """
    import re

    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text()

    defaults = re.findall(r"EXTRACTOR_MODEL:\s*\$\{EXTRACTOR_MODEL:-([^}]+)\}", compose)
    assert defaults, "no EXTRACTOR_MODEL default found in docker-compose.yml"

    ineligible = sorted({d for d in defaults if d not in US_ORIGIN_MODELS})
    assert not ineligible, (
        f"docker-compose.yml defaults EXTRACTOR_MODEL to {ineligible}, which ADR-020 "
        f"excludes. The allowed set is {sorted(US_ORIGIN_MODELS)}."
    )

    assert set(defaults) == {Settings(_env_file=None).extractor_model}, (
        f"compose defaults {sorted(set(defaults))} disagree with the application "
        f"default {Settings(_env_file=None).extractor_model!r}. They must agree, or "
        "the model a container requests is not the model anything else describes — "
        "and `ollama-pull` would pull one model while the worker asked for another."
    )


def test_no_recorded_floor_is_unfailable():
    """A floor of 0.0 cannot be scored below, so recording one converts the gate
    from "measure this adapter" into "pass unconditionally".

    `FLOORS["null"] = {0.0, 0.0, 0.0}` was exactly that, and it disarmed both of
    the loud skips in `test_the_configured_extractor_clears_its_floors` at once:
    a recorded entry makes `floors is None` false, and the null adapter also
    bypasses the model-reachability skip because that one is guarded on
    `extractor_adapter != "null"`. `Settings()` resolves to the null adapter by
    default, which is what CI runs — so the project's headline extraction gate
    reported green while measuring nothing, on every push, for as long as the
    entry existed. The two "THE EXTRACTION GATE DID NOT RUN" messages were
    written to make precisely that impossible.

    An adapter with no floors is the honest state: the gate skips and says so.
    """
    unfailable = {
        adapter: floors
        for adapter, floors in FLOORS.items()
        if all(value == 0.0 for value in floors.values())
    }

    assert not unfailable, (
        f"these adapters are recorded with floors nothing can score below: "
        f"{sorted(unfailable)}. Remove the entry so the gate skips loudly "
        f"instead of passing green."
    )
