# STORY-090: Review's empty queue names its upstream cause

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a reviewer opening an empty queue, I want to know whether I am caught up or whether nothing
upstream could have produced a proposal, so that an empty screen is not read as an all-clear.

## Context

Review says "Nothing is waiting for review." It says that in two very different situations: every
proposal has been decided, and no proposal could exist at all because no pair of editions both
hold obligations. On 2026-08-26 the live graph was in the second state — one edition with 114
obligations, three with none — and the screen read as the first.

This is the exact shape [ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md) and
STORY-067 fixed on Triage, where an empty table had to say how many changes it was not showing
and why. It recurs here because those fixes touched Triage and not Review. Sprint 6's Triage fix
closed a third instance of the same family: a screen telling the truth in a way a reader will
misread.

## Acceptance criteria

- [ ] Given no edition in the corpus holds obligations, **When** a reviewer opens Review,
      **Then** the screen says the queue cannot be filled yet and why, not that nothing is
      waiting.
- [ ] Given obligations exist but only one document holds any, **Then** the screen says a
      proposal needs both sides and names what is missing.
      *(Redefined 2026-09-11 by the pairing design. As written this criterion said "no two
      editions of a document both hold them", which was the trigger while a proposal could run
      between two editions of one instrument. `propose_links` now skips any pair sharing a
      document — that question is the diff's — so a document with two obligation-holding editions
      is exactly the configuration that can no longer produce a proposal, and treating it as the
      caught-up case would be the false all-clear this story exists to prevent. The count behind
      the criterion changed with it: `documents_comparable` → `documents_with_obligations`, and
      the screen branches on fewer than two.)*
- [ ] Given proposals existed and have all been decided, **Then** "nothing is waiting" is still
      the answer, and it is distinguishable from the two cases above.
- [ ] The wording does not require a reader to know what a proposal is made from — the same bar
      Triage's message meets.

## Dependencies

- The counts it needs may already be reachable; if not, this grows a small read on the review
  route. That is the one thing that could take it above S, and it should be checked first.

## Open questions

- Does Review need its own counts, or can it ask the same question Triage already answers? Two
  screens deriving the same fact two ways is how they drift apart.
