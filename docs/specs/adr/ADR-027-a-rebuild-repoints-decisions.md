# ADR-027: A rebuild re-points decisions across a change of identity

**Status:** Accepted · **Date:** 2026-08-24 · **Deciders:** Project owner
**Extends:** [ADR-014](ADR-014-proposals-and-decisions-are-different-things.md)

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

Identity in this codebase is layered, and each layer feeds the next:
`chunk_id = sha256(version_id | section_path | occurrence | ordinal)[:32]`,
`obligation_id = sha256(version_id | section_path | normalize(statement))[:32]`, and
`decision_key = sha256(source_obligation_id | target_obligation_id)[:32]`. Changing a chunk's
`section_path` — exactly what a chunker improvement does, and exactly what STORY-063 does —
therefore re-keys every obligation extracted from that chunk, because `section_path` sits
inside `obligation_id`'s own hash. An obligation with a new id is not the same node the old
`:LinkDecision` rows point at, so a rebuild that re-keys obligations strands every recorded
verdict about them: the `:LinkDecision` node survives, but `replay_decisions` can no longer find
a matching pair of obligation ids to apply it against, and the `IMPLEMENTS` edge the approval
once produced stops being written.

[ADR-014](ADR-014-proposals-and-decisions-are-different-things.md) holds that a `:LinkDecision`
is canonical because it records a fact a human established, not something derived that a
rebuild may discard. A re-key does not make that fact untrue — the reviewer still approved that
one obligation implements that other one — it only changes the hash the system uses to find it.
Treating a stranded decision as though it had never been made would silently undo review work
for no reason connected to the review itself.

## Decision

**A rebuild re-points stranded decisions.** The old obligation id maps to the new one through
the statement, which the change does not move: `section_path` shifts, `normalize(statement)`
does not, so the statement is the stable handle a repair can hold onto while the id built from
it changes underneath. The mapping is captured inside the rebuild's own write transaction,
reading the edition's obligations *before* `drop_obligations` runs and pairing them against the
newly written set afterwards — it has to happen there, because `:LinkDecision` stores no
statement of its own, only obligation ids and a verdict, and the node carrying the old
statement is exactly what the drop deletes.

**Where a re-pointed decision's new `key` collides with a decision that already exists, the
existing verdict wins and the stale one is left unrepaired.** `link_decision_key_unique`
constrains `:LinkDecision.key`, so re-pointing a decision onto a key another decision already
holds cannot write both. Two human verdicts are never silently merged into one; when this
happens, the older decision keeps deciding and the one that lost the collision is left
unrepaired rather than overwriting or being overwritten. If that stranded decision is an
*approval*, `unpromotable` counts it; if it is a rejection, nothing counts it — see
**Makes hard** below. (Both are counted now: `rejections_stranded` closed that gap, and the
superseding note under **Makes hard** records what else has changed since.)

## Consequences

**Makes easy.** Rebuilds stop costing review decisions, and this holds for every future
chunker change, not only the one motivating it — the repair lives inside `replay_decisions`,
which every rebuild already runs, rather than in code specific to this one re-key.

**Makes hard.** A decision whose *statement* changed, not merely its `section_path`, is not
repairable this way: the statement is the only thread connecting an old obligation id to a new
one, and if the statement itself moved there is nothing left to match on. The same holds for a
statement two obligations share: `obligation_id` hashes `section_path` as well, so one sentence
appearing in two sections is two distinct nodes, and a statement that names two ids identifies
neither. Both of those fall through unrepaired.

**The safety net under them only covers approvals.** `UNPROMOTABLE` filters
`{verdict: 'approve'}`, so an unrepaired approval is counted and an unrepaired *rejection* is
counted nowhere — a rebuild reports it neither as replayed nor as stranded. This ADR is
recording the gap rather than closing it: widening the count is a behaviour change, and
"unpromotable" would then be the wrong name for what it holds, since a rejection was never
going to promote anything. That is its own item, and the requirement below is about the count
that does exist.

> **Superseded on 2026-09-11, twice over.** STORY-076 closed the gap this section records:
> `REJECTIONS_STRANDED` counts an unrepaired rejection, and `replay_decisions` returns it as
> `rejections_stranded` beside `unpromotable`. The two stayed separate for the reason argued
> above — "unpromotable" is the wrong name for a verdict that was never going to promote — and
> because the losses differ: a stranded approval leaves a link missing and the proposal returns
> to the queue, while a stranded rejection leaves a suppression nobody applies, so the proposal
> returns and nothing tells the reviewer they already refused it.
>
> The pairing split then added a second decision vocabulary. `:PairingDecision` repoints through
> the same path (its schema parameterises the label, both property names and the key function),
> and `pairing_decisions_stranded` counts `paired` and `distinct` together in ONE number — not
> the link side's two. That is deliberate, not an oversight: both pairing verdicts lose the same
> way, the pair simply returns to the queue unanswered, so there is no second event to name. The
> link side's split exists because STORY-076 had to retrofit one.
>
> What stands unchanged is everything above this note about *which* decisions fall through
> unrepaired — a moved statement, or a statement two obligations share — and the requirement
> below that the count be on screen rather than merely returned.
>
> **That requirement is not yet met for the new count.** `unpromotable` and
> `rejections_stranded` are rendered on the rebuild panel; `pairing_decisions_stranded` is
> returned by the rebuild and displayed nowhere. By this ADR's own argument that is the state it
> exists to forbid — a rebuild that repaired most decisions and said nothing about the rest looks
> complete in exactly the case where it is not. The pairing screen task owes it.

The count that does exist is why this ADR requires `unpromotable` to be on screen rather than
merely returned by the API — a rebuild that silently repaired most decisions and said nothing
about the rest would look complete in exactly the case where it is not.

## Alternative rejected

**A one-shot migration script.** Something a person must remember to run exactly once against a
graph whose state cannot be verified afterwards, and which does nothing for the next chunker
change — the same repair would have to be written again, or, more likely, not written again
until the next audit found the same gap. Putting the repair in `replay_decisions` instead means
it fires on every rebuild by construction, with no step for anyone to forget.

## Extends

[ADR-014](ADR-014-proposals-and-decisions-are-different-things.md). This ADR supersedes
nothing: ADR-014's decision that a `:LinkDecision` is canonical and outlives the derived layer
is what makes a stranded decision worth re-pointing in the first place. This ADR states how a
rebuild honours that guarantee when the identity underneath a decision moves.
