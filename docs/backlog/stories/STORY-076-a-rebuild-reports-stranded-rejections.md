# STORY-076: A rebuild says how many rejections a re-key stranded

**Epic:** — · **Status:** Ready · **Estimate:** S

## User story

As a reviewer whose rejection was lost by a re-extraction, I want the rebuild that lost it to say
so, so that a decision I recorded does not disappear without anything counting it.

## Context

`UNPROMOTABLE` in `backend/src/policy_grapher/links/decisions.py` filters `{verdict: 'approve'}`.
A rebuild therefore reports approvals it could no longer apply — `unpromotable` — and says
nothing at all about **rejections** whose obligations the re-key moved beyond repair.
[ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) records the gap in its own
consequences.

The asymmetry matters more than it looks. An approval that cannot be applied leaves a link
missing, which the reviewer will meet again in the queue. A rejection that cannot be applied
leaves a **suppression nobody is applying** — the proposal comes back, and the reviewer has no
way to know they already refused it. The verdict is not merely lost; it is silently reversed.

**Two things had to be decided together, and this story takes both**, which is why it is an S
rather than a row waiting for a decision.

*What is reported:* a distinct count, `rejections_stranded`, beside `unpromotable`. Not folded
into `unpromotable`, because that name means "was going to promote and could not" and a rejection
was never going to promote anything. Not a queue item asking the reviewer to re-decide either —
that is a larger feature, it presumes the reviewer wants to be asked again, and it can be built
on this count later if anyone does.

*What it is called:* `rejections_stranded`, because "unpromotable rejections" is a contradiction
in the vocabulary this project already uses.

## Acceptance criteria

- [ ] A rebuild reports `rejections_stranded` in its counts, alongside `unpromotable`.
- [ ] Given a recorded rejection whose source or target obligation no longer exists after
      re-extraction, **When** the edition is rebuilt, **Then** that count is incremented.
- [ ] Given a rejection the rebuild could still apply, **Then** it is applied and not counted as
      stranded — the count is about loss, not about rejections in general.
- [ ] The count reaches the screen with the other rebuild counts, and its label says what it
      means: a refusal that will not be applied, so the proposal can return.
- [ ] A test asserts the two counts move independently — a stranded approval must not increment
      the rejection count and vice versa.

## Dependencies

- [ADR-027](../../specs/adr/ADR-027-a-rebuild-repoints-decisions.md) and the re-pointing it
  describes — landed in sprint 6.
- **Newly reachable:** until 2026-08-27 no `:LinkDecision` existed at all, so this could not be
  observed. One does now, and rejections can be recorded through the UI.

## Open questions

- Should a stranded rejection be listed individually, the way rejected chunks are, rather than
  only counted? The criteria above say counted, because a reviewer cannot act on the detail —
  the obligation it referred to is gone. If the count turns out to be routinely non-zero, that
  answer should be revisited.
