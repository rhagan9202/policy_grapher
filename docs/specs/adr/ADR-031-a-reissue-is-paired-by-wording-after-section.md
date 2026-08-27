# ADR-031: A reissue's edits are paired by wording, after section fails

**Status:** Accepted · **Date:** 2026-08-27 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

**Amends [ADR-015](ADR-015-changes-are-detected-and-ranked.md)**, which pairs by section only.
Everything else ADR-015 decided — what a `:Change` is, how rows are ranked, that unlinked changes
are counted out loud — stands.

## Context

ADR-015 finds a `MODIFIED` by structure: a section holding exactly one unmatched clause on each
side has been edited. Its reasoning is stated plainly and still holds — "pairing two against two
is a guess, and a wrong guess points a reviewer at the wrong sentence with no indication that it
did."

It has one failure mode, and the corpus produces it. Diffing the 2018 and 2020 editions of DoDD
5000.01 gives **0 MODIFIED, 11 ADDED, 80 REMOVED**. The two editions are structurally rewritten —
DoD renumbered enclosures into sections between them — so almost no section holds exactly one
unmatched clause on each side and the pairing never fires. To a reviewer it reads as "the whole
document was replaced", which is the least actionable answer the product can give and is also
untrue: most of those clauses are the same duties, renumbered and lightly reworded.

**The constraint that matters is not "no text similarity". It is that a row must be explainable
by a path a person can walk.** ADR-015 says so in the sentence next to it: nothing on the triage
path is a model call. A lexical measure satisfies that constraint. A model call would not.

**And this project already has one.** `links/propose.py` pairs obligations across documents by
shared content words, weighted by shared designators, scored against the *shorter* statement's
vocabulary, and it emits a rationale a reviewer reads — "they share 100% of the shorter clause's
distinctive wording (acquire, competition, equipment, services, statutory, subsystems)". That is
the Review queue's whole basis and it has been in use since sprint 4.

## Decision

**A second pass pairs by wording what section-based matching left unmatched, using the same
lexical measure the proposer already uses.**

1. **Section-based pairing runs first and is unchanged.** A section holding exactly one unmatched
   clause on each side is still a `MODIFIED`, and still on structural grounds alone.
2. **What it leaves over goes to a second pass**, scored with `links/propose.py`'s measure. The
   best-scoring pair above the threshold is a `MODIFIED`; the rest stay `ADDED` and `REMOVED`.
3. **The threshold is higher than the proposer's**, and deliberately so. The proposer offers a
   candidate to a human who will accept or reject it; this writes a `MODIFIED` nobody reviews.
   The cost of a wrong answer is not symmetric, so the bar is not the same.
4. **Every pair carries its evidence.** A `MODIFIED` found this way records the shared wording
   that produced it, in the same words the Review queue uses, and the screen shows it. A row a
   reader cannot interrogate is exactly what ADR-015 refused to produce.
5. **Ambiguity still falls back.** If two candidates score within a hair of each other, both stay
   `ADDED`/`REMOVED` and the summary says so — ADR-015's answer to "we do not know", kept.

## Consequences

**What this buys.** The 2018/2020 diff stops reading as wholesale replacement. Renumbering — the
single most common thing that happens to a DoD issuance between editions — stops looking like
deletion.

**What it costs, and this is the real risk.** A false pairing reports a `MODIFIED` that never
happened, and a reviewer who trusts it reviews a change that does not exist. That is worse than
the over-reporting the current fallback produces, because over-reporting is visible and a wrong
pairing is not. Three things hold it back: the higher threshold, the recorded evidence, and the
ambiguity fallback. **If those prove insufficient the remedy is to raise the threshold, not to
lower it** — the same sentence ADR-023 and ADR-030 both end on.

**What it does not change.** No model call enters the triage path. Ranking is untouched. Unlinked
changes are still counted out loud. A section that pairs structurally still pairs structurally,
so the cheap and certain answer is still preferred to the inferred one.

**Why not similarity everywhere.** Replacing section-based pairing rather than following it would
throw away a signal that is *certain* — a section with one clause each side has been edited, and
no measurement improves on that. The order matters: structure first, wording only for what
structure cannot reach.
