# ADR-014: A proposal and a decision are different things

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md) put obligations in the graph, derived
from chunk text by a model behind a port. This phase connects them: an obligation in one of our
own issuances is said to *implement* an obligation in a higher-tier one, and that link is what
the whole deliverable rests on. Impact triage — *a higher-level policy changed; which of our
policies are affected?* — is a single traversal from a changed higher obligation, down an
`IMPLEMENTS` edge, to ours. Every answer the tool gives is only as good as those edges.

Nothing can establish them reliably by machine. The proposer this phase ships is lexical overlap
plus shared issuance designators, and its output is visibly weak: run over two real DoD
issuances it proposes four links, and reading them, they are related by vocabulary rather than
by obligation. A better proposer is possible — Phase 6's hybrid retrieval will be one — but no
proposer good enough to be trusted unreviewed is available, and a compliance answer built on an
unreviewed machine inference is worse than no answer, because it is confident.

So a human decides. That creates the problem this ADR exists to solve. The layer these links
live in is *derived* — droppable and rebuildable by construction, because a better chunker or a
better extractor must be able to replace it wholesale (ADR-012). But a human's verdict is not
derived from anything. If it lived in that layer, every re-extraction would silently discard
every review anyone had ever done: no error, no log line, just a review queue that has
mysteriously refilled with work someone already did.

## Options considered

**One `IMPLEMENTS` edge with a `status` property.** `status: 'proposed' | 'approved'`. One
relationship type, one place to look. Rejected: it makes every consumer responsible for
remembering to filter, and the first query that forgets presents a machine guess as an approved
fact. The triage traversal is the query that matters most and the one most likely to be written
from memory or copied from the design doc. A property is a convention; conventions are what get
forgotten under deadline.

**Verdicts as properties on the edge.** `approved_by`, `approved_at` on the `IMPLEMENTS_PROPOSED`
edge itself. Simple, no extra node. Rejected for the reason above: the edge is derived, so a
rebuild drops it, and the properties go with it. The whole point is that the verdict must
outlive the thing it is about.

**Two edge types plus a canonical decision node.** `IMPLEMENTS_PROPOSED` (derived,
machine-authored) and `IMPLEMENTS` (written only by replaying a human verdict), with the verdict
itself in a `:LinkDecision` node keyed by content. Chosen.

## Decision

**Two relationship types, never one with a status property.** `IMPLEMENTS_PROPOSED` is what the
proposer writes; `IMPLEMENTS` is what a human's approval produces. The triage query names
`IMPLEMENTS` and therefore *cannot see* a proposal — the mistake is not merely discouraged, it is
unwriteable. `propose_links` has no statement that mentions `IMPLEMENTS`, and a test asserts the
`IMPLEMENTS` count is zero after proposing, so the invariant is checked rather than assumed.

**`:LinkDecision` is canonical.** It is a node, not a property, precisely because properties live
on the thing they annotate and the thing here is droppable. Nothing in `links/rebuild.py` deletes
one; the rebuild *replays* them. It carries `verdict`, `actor`, `at`, `rationale`, and both
obligation ids.

**Rejections are stored, not just approvals.** A rebuild that resurrects a link someone already
rejected is worse than one that forgets an approval: forgetting an approval leaves an obvious
gap, while resurrecting a rejection silently re-adds work a human already did and dismissed,
looking exactly like new work. `replay_decisions` therefore *deletes* any `IMPLEMENTS` edge for a
rejected pair rather than merely declining to create one — a pair can have been approved before
it was rejected, and not-creating would leave the old edge standing.

**The decision key is content-derived and directional.** `hash(source_obligation_id,
target_obligation_id)`, where both ids are themselves content-derived (ADR-013). That is the
entire reason a rebuild can find its way back: an internal node id is reassigned every time the
node is dropped and recreated, so a key built from one would orphan every verdict on the first
rebuild. It is directional because "A implements B" is not "B implements A", and a symmetric key
would let a verdict on one direction silently decide the other.

**`replay_decisions` is the only writer of `IMPLEMENTS` anywhere in the codebase.** Nothing
promotes a link directly — not the proposer, not the review route, not the rebuild. The route
records a verdict and then calls replay; the rebuild re-proposes and then calls replay. One
writer means one code path to audit when someone asks how a particular edge came to exist.

**Replay reports what it could not do.** `replay_decisions` returns `promoted`, `suppressed` and
`unpromotable`. The third counts approvals whose obligations no longer both exist — the case
where an extractor change stops producing one side of a link a human approved. The decision stays
recorded, because it remains a fact a person established; the graph simply cannot express it. A
rebuild that returned only `promoted: 4` would look complete in exactly the situation where a
human decision has quietly stopped being represented, so the count is returned and a test pins
it.

**The actor is the authenticated principal and nothing else.** `POST /review/{source}/{target}`
takes `{verdict, rationale}`. `VerdictIn` has no `actor` field, and a body that supplies one has
it discarded — a client-supplied actor would let anyone record a decision as anyone, which makes
the audit trail worthless at the moment it matters most. Both review routes require a principal;
`POST` is the route in this codebase that writes an audit record.

**The queue shows both sides with their citations.** Document name, `section_path` and page for
each obligation. This is not presentation polish: a reviewer asked whether one clause implements
another cannot answer without going and reading both in context, and a queue that made them
search for the passage would be a queue that gets rubber-stamped.

**The queue shows one citation per side, not one row per anchor.** Chunk overlap repeats a
sentence across a section split, so an obligation can legitimately anchor to more than one chunk
— measured at 5 of 88 obligations on `500001p_2003.pdf`. A plain traversal would emit a row per
combination and hand the reviewer the same pair several times; the second verdict then has
nothing left to decide, and the queue length stops meaning how much work is outstanding. The
citation is the earliest anchoring chunk in reading order, because that is where the passage
starts.

**A verdict on a pair that was never proposed is a 404.** A decision is recorded against a
proposal, not against an arbitrary pair of ids, so junk cannot accumulate in the canonical layer
through a mistyped request.

**One reviewer is sufficient per link** — confirmed by the project owner on 2026-08-20. No second
approver, no segregation of duties. Note for whoever revisits this: `:LinkDecision` is keyed on
the *pair*, so it holds exactly one current verdict, and dual approval would need a key that also
included the actor. That is a schema change, but a small and mechanical one — the decision node
already carries the actor, and nothing outside `record_decision` and `replay_decisions` reads its
shape.

**Re-deciding replaces rather than appends.** A reviewer who changes their mind leaves one
current verdict, not two contradictory records for a replay to arbitrate between. The cost is
that decision *history* is not kept: this codebase can say what was decided and by whom, not what
was decided previously and reversed. If a control framework later needs that, it is the same
schema change as dual approval.

## Consequences

**Makes easy.** Phase 5's propagation traversal can name `IMPLEMENTS` and be correct by
construction — there is no filter to forget. Improving the proposer is now a low-risk change:
its output cannot reach a compliance answer without passing a human, so a bad proposal costs
review time rather than correctness. Re-extracting an entire corpus is safe to do casually,
which is what makes the derived layer's rebuildability worth having at all.

**Makes hard.** Every link needs a human, and the proposer is weak enough that many of the
proposals a reviewer sees will be rejections. That is the intended trade — but it means the
review queue's throughput, not extraction quality, is the practical ceiling on how much of the
corpus is usable for triage. Nothing in this phase reduces that; a better proposer (Phase 6)
directly attacks it, by raising the fraction of the queue worth approving.

**Commits us to.** `IMPLEMENTS` having exactly one writer, permanently. The moment a second
piece of code writes that edge — a bulk-import script, a migration, a "just this once" fixup —
the guarantee that every such edge traces to a recorded human verdict is gone, and it is gone
silently, because the edge looks identical either way. It also commits the project to the
distinction between canonical and derived being a real boundary rather than a description:
`:LinkDecision` is the first node whose whole purpose is to survive a rebuild, and every future
human-authored artefact — an override, an annotation, an exception — belongs on its side of that
line, keyed by content rather than by node id.
