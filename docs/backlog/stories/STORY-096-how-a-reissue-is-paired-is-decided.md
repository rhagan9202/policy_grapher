# STORY-096: How a reissue's edits are recognised is decided

**Epic:** — · **Status:** Done · **Estimate:** S

## User story

As a maintainer about to change how editions are diffed, I want the pairing rule written down
first, so that the implementation argues from a recorded decision rather than inventing one and
discovering the question halfway through.

## Context

The decision half of [STORY-047](STORY-047-reissues-read-as-replacement.md), split out because
three of that story's five acceptance criteria are decisions rather than code — a similarity
threshold, whether [ADR-015](../../specs/adr/ADR-015-changes-are-detected-and-ranked.md) is
superseded, and what Triage does with the result. Sprint 7 proved the pattern works: STORY-087
wrote ADR-030 and STORY-088 implemented it, and the implementation had an answer for every
question that came up because the decision existed first.

The problem is real and measured. Diffing the 2018 and 2020 editions of DoDD 5000.01 produced
**0 MODIFIED, 11 ADDED, 80 REMOVED**. That is ADR-015's documented fallback behaving exactly as
designed: the two editions are structurally rewritten, so no `section_path` held exactly one
unmatched obligation on each side and the section-based pairing never fired. To a reviewer it
reads as "the whole document was replaced", which is the least actionable answer available.

ADR-015 chose section-based pairing deliberately, and its reasoning still holds: **nothing on the
triage path is a model call**, so every row is explained by a path a person can walk. Any
similarity measure has to keep that property or explicitly give it up, and giving it up is a
decision about what this product is, not a tuning parameter.

## Acceptance criteria

- [ ] An ADR is written and committed deciding how an obligation that moved between sections is
      recognised as the same obligation reworded.
- [ ] It states whether the pairing stays explainable without a model call, and if it does not,
      says what is given up and why that is worth it.
- [ ] It says what happens when a pairing is ambiguous — ADR-015's current answer is to report a
      removal and an addition and say so, which is honest and which any replacement has to at
      least match.
- [ ] It records the measured numbers it argues from: 0 MODIFIED, 11 ADDED, 80 REMOVED on the two
      DoDD 5000.01 editions.
- [ ] It supersedes or amends ADR-015 explicitly rather than sitting beside it, since the two
      speak to the same rule.
- [ ] It says what a false pairing costs. A wrongly paired obligation reports a MODIFIED that
      never happened, and a reviewer who trusts it reviews a change that does not exist — which
      may be worse than the over-reporting the current fallback produces.

## Dependencies

- None. It argues from measurements already taken.

## Open questions

- None. Taking them is the item.
