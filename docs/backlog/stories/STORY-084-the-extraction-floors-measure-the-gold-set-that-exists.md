# STORY-084: The extraction floors are measured against the gold set that exists

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a maintainer swapping or upgrading the extraction model, I want the ratchet's floors to be
measured against the current gold set, so that a red build means the model got worse rather than
that the gold set moved underneath it.

## Context

Sprint 5's retrospective assigned this to sprint 6 and
[ADR-025](../../specs/adr/ADR-025-will-is-a-modality-and-bindingness-is-derived.md) records that
it was not done: the floors were set over three fixtures and six obligations, before `WILL`
existed as a modality, and now guard a four-fixture, twelve-obligation gold set that contains
`WILL` labels. The comment above `FLOORS` says so itself — "**They pass by zero margin**", and
"widening the gold set is the prerequisite for treating this as a real gate."

**The prerequisite landed on 2026-08-26, immediately before this sprint.** `FLOORS["null"]` was
`{0.0, 0.0, 0.0}`, which no score can fall below; because an entry existed, the gate's
`floors is None` skip never fired, and because the null adapter also bypasses the
model-reachability skip, both "THE EXTRACTION GATE DID NOT RUN" messages were disarmed. The gate
reported green on every CI run while measuring nothing. Removing the entry restored the loud
skip. Re-measuring without that fix would have set honest floors behind a gate that still could
not apply them.

## Acceptance criteria

- [ ] The floors for `local:llama3.1:8b` are re-measured against the current gold set with a
      real model reachable, and the observed numbers are recorded in the commit message.
- [ ] The recorded floors are set from that measurement, not estimated.
- [ ] Given the gate runs with a real model, **When** the model scores below a floor, **Then**
      the failure names which leg fell and by how much.
- [ ] `modality_accuracy` is set with the same caution the existing comment describes — not
      raised to an observed 1.000 computed over too few matched pairs, because a floor that
      fires on noise teaches people to ignore it.
- [ ] The gold set covers every member of `Modality`, asserted the way `test_triage.py` already
      asserts the weight table's keys equal the enum's members.

## Dependencies

- The `FLOORS["null"]` removal — **landed 2026-08-26**, before this sprint opened.
- Needs Ollama reachable with `llama3.1:8b`. It is, on the development host.

## Open questions

- None. The measurement decides the numbers.
