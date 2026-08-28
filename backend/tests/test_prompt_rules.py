"""ADR-036: a checkable prompt rule is checked, and the link is asserted.

Four sprints running, the extraction prompt stated a rule that nothing enforced.
Each went unenforced for at least one sprint. Each was found by looking at
extracted data rather than by a test — the modality word (sprint 7, 18 of 215
obligations were headings labelled SHALL), word-for-word quoting (sprint 9, 34 of
196), the placeholder actor (sprint 9, 20 obligations), and the actor copied from
the statement (sprint 10, 14 of 123). Each was then fixed deterministically in
`schema.py` in under an hour, because each was checkable all along.

A prompt is a string. Nothing executes it and nothing related its sentences to
the validators, so a rule that was merely written read exactly like a rule that
held. These tests are what make writing an unenforced rule fail before it ships
rather than a sprint later in the data.
"""

import re

from policy_grapher.extraction import schema
from policy_grapher.extraction.prompt import EXTRACTION_PROMPT, PROMPT_RULES


def _normalised(text: str) -> str:
    """Whitespace-folded, because the prompt is wrapped and its sentences are not."""
    return re.sub(r"\s+", " ", text).strip()


def test_every_registered_rule_is_still_in_the_prompt():
    """The half of the link that catches a prompt edit.

    Rewording a rule without revisiting the registry fails here, which is the
    only thing stopping the registry from becoming a description of a prompt that
    no longer exists.
    """
    prompt = _normalised(EXTRACTION_PROMPT)

    missing = [rule.id for rule in PROMPT_RULES if _normalised(rule.sentence) not in prompt]

    assert not missing, (
        f"{len(missing)} registered rule(s) are no longer in the prompt: {missing}. "
        f"If the wording changed, update the registry; if the rule is gone, remove it."
    )


def test_every_rule_is_either_enforced_or_explained():
    """The half that catches a new rule.

    Exactly one of the two, so a rule cannot be added without someone deciding
    which it is. `unenforceable` is a first-class answer — roughly half these
    rules need judgement — but it has to give a reason, because a registry that
    accepted a shrug would push people to write bad validators to get past it.
    """
    for rule in PROMPT_RULES:
        has_validator = rule.enforced_by is not None
        has_reason = rule.unenforceable is not None
        assert has_validator != has_reason, (
            f"rule {rule.id!r} must have exactly one of enforced_by or "
            f"unenforceable, not {'both' if has_validator else 'neither'}"
        )
        if has_reason:
            assert len(rule.unenforceable.split()) >= 8, (
                f"rule {rule.id!r} is marked unenforceable without a reason worth "
                f"reading: {rule.unenforceable!r}"
            )


def test_every_named_validator_exists():
    """A rule may not name a validator that was renamed or deleted.

    This asserts a link, not a correctness: it cannot tell whether the validator
    implements the rule it is registered against. A wrong validator passes here.
    That limit is stated in ADR-036 rather than left for someone to assume away.
    """
    for rule in PROMPT_RULES:
        if rule.enforced_by is None:
            continue
        target, _, attribute = rule.enforced_by.partition(".")
        assert hasattr(schema, target), (
            f"rule {rule.id!r} names {rule.enforced_by!r}, but "
            f"`extraction.schema` has no {target!r}"
        )
        if attribute:
            owner = getattr(schema, target)
            has_it = hasattr(owner, attribute) or attribute in getattr(
                owner, "model_fields", {}
            )
            assert has_it, (
                f"rule {rule.id!r} names {rule.enforced_by!r}, but {target!r} has "
                f"no {attribute!r}"
            )


def test_the_rules_have_distinct_ids():
    ids = [rule.id for rule in PROMPT_RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {sorted(ids)}"
