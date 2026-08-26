# STORY-085: The ranking weights ADR-025 records are asserted, not just commented

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a reviewer relying on Triage's ranking, I want the modality weights to be pinned by a test,
so that a one-character edit cannot silently move the corpus's dominant binding modality to the
bottom of every ranked list.

## Context

[ADR-025](../../specs/adr/ADR-025-will-is-a-modality-and-bindingness-is-derived.md) decided that
`WILL` is as binding as `SHALL` in this corpus, and `MODALITY_WEIGHT` carries a six-line
justification saying so. Nothing asserts the value.

`test_every_modality_the_schema_allows_has_a_weight` checks that the weight table's *keys* equal
the enum's members — which sprint 5's retrospective praises, correctly, for catching `WILL`'s
addition within a minute. It says nothing about the *values*. Changing `WILL`'s weight sends the
modality this corpus uses most to the bottom of every Triage ranking with the whole suite green.

This is the shape of the ADR-020 defect sprint 4 found: a decision recorded in a comment,
believed to be enforced, enforced nowhere.

## Acceptance criteria

- [ ] A test asserts `MODALITY_WEIGHT["WILL"] == MODALITY_WEIGHT["SHALL"]`, citing ADR-025.
- [ ] The weight table is asserted as an explicit expected mapping, so a changed value fails and
      names the modality that changed.
- [ ] The test's failure message says what the ranking consequence is, not only that two numbers
      differ.

## Dependencies

- None. `MODALITY_WEIGHT` and the gold set both already exist.

## Open questions

- None. ADR-025 already took the decision; this only enforces it.
