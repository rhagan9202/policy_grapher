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
happens, the older decision keeps deciding and the one that lost the collision falls through to
`unpromotable` rather than overwriting or being overwritten.

## Consequences

**Makes easy.** Rebuilds stop costing review decisions, and this holds for every future
chunker change, not only the one motivating it — the repair lives inside `replay_decisions`,
which every rebuild already runs, rather than in code specific to this one re-key.

**Makes hard.** A decision whose *statement* changed, not merely its `section_path`, is not
repairable this way: the statement is the only thread connecting an old obligation id to a new
one, and if the statement itself moved there is nothing left to match on. That decision still
lands in `unpromotable`, correctly, and is why this ADR requires that count to be on screen
rather than merely returned by the API — a rebuild that silently repaired most decisions and
said nothing about the rest would look complete in exactly the case where it is not.

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
