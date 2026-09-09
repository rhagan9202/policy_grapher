# Pairing is not implementing: splitting a relationship that was carrying two jobs

**Status:** Design · **Date:** 2026-09-09 · **Sprint:** — (found in the sprint-12 acceptance walkthrough)

Comes out of a live review of the containerised stack against 119 real proposals produced by
`llama3.1:8b` and `lexical-v1`. Three of the four gaps that walkthrough found are fixed and
verified; this document is the fourth, which is structural rather than a defect.

## The problem, restated in one paragraph

`IMPLEMENTS` is being asked to mean two different things. Triage reads it as *"our lower-tier
clause discharges that higher-tier duty"* and traverses `(ours)-[:IMPLEMENTS]->(higher)` where
`higher` is the changed obligation in the newer edition. Review, as the UI can currently drive
it, produces something else entirely: the build screen's *Propose links against* fieldset is
populated from `listVersions(slug)`, so the only candidates it can offer are **other editions of
the same document**. Every proposal the UI can generate therefore runs `newer → older` within one
instrument, which is inverted for Triage's traversal and semantically a different claim. The
reviewer's work is real, recorded, permanent — and unreachable by the screen it exists to feed.

## What the investigation changed about the obvious answer

The obvious answer is "stop offering same-document candidates". It is wrong, and the reason is
worth stating because it is not visible from the code alone.

**`changes/diff.py` already owns same-document pairing.** It diffs two editions into `:Change`
nodes and a `MODIFIED` change carries `previous_statement` — the pairing, recorded. ADR-031
governs how that pairing is made: by section path and normalized statement, never by text
similarity, because *"pairing two against two is a guess, and a wrong guess points a reviewer at
the wrong sentence with no indication that it did."*

**But the section rule cannot survive a restructure, and DoD issuances restructure.** Measured on
the live graph, the two editions of DoDD 5000.01 share no top-level section vocabulary at all:

| edition | top-level sections |
| --- | --- |
| `dodd-5000-01@2018-08-31` | `ENCLOSURE 1` (63), `4` (12), `5` (6), `3` (2) |
| `dodd-5000-01@2022-07-28` | `SECTION 1` (40), `SECTION 2` (34) |

`ingest.py` calls these the legacy and modern formats and detects them explicitly. The diff paired
17 clauses and left 123 as 66 `REMOVED` plus 57 `ADDED` — not because the clauses are unrelated
but because their section names changed. The lexical proposer is the only mechanism in the system
that can pair them, and it demonstrably does:

```
now    : "Acquisition professionals will seek, develop, and implement initiatives…"
before : "Throughout the Department of Defense, acquisition professionals shall …"
```

So the same-document job is real and needed. What is wrong is where its output goes. A third
relationship — the first shape this design took — would have made it worse, because the graph
would then record the same fact in three places (`Change`, `IMPLEMENTS_PROPOSED`, and the new
one) with nothing obliging them to agree.

## Decision

**A human-confirmed same-document pairing resolves into the diff, and `IMPLEMENTS` becomes
strictly cross-document.**

### 1. Two decisions, two closed vocabularies

| | Pairing | Implements |
| --- | --- | --- |
| Question | is the newer clause the reworded older one? | does our clause discharge that duty? |
| Scope | one document, two editions | two documents |
| Canonical node | `:PairingDecision` (new) | `:LinkDecision` (unchanged) |
| Verdict | `paired` / `distinct` | `approve` / `reject` |
| Effect | `ADDED`+`REMOVED` → `MODIFIED` | promotes `IMPLEMENTS` |

Separate vocabularies rather than reusing `approve`/`reject`: ADR-014 closed that vocabulary
because `replay_decisions` branches on it, and a verdict meaning "these are the same clause" is
not an approval of anything. Two node types keep both branches exhaustive over their own domain.

**Direction is fixed and matches the diff's.** `from` is the older edition, `to` the newer, the
same orientation `:Change`'s `FROM_VERSION`/`TO_VERSION` already uses and the same one
`GET /triage?to_version_id=` takes. A pairing is stored once, in that orientation, so the same two
clauses cannot be paired twice in opposite directions.

**Identity is a hash of the two obligation ids**, as `:LinkDecision`'s `key` is — computed in
Python and stored alongside both ids, because Cypher cannot recompute it and the anti-join needs
the ids to be readable. This is the existing pattern in `links/decisions.py` and the reason it is
there applies unchanged.

### 2. The split is made at proposal time

`propose_links` reads both sides' obligations already. `READ_OBLIGATIONS` gains the owning
document, and the function emits `PAIRING_PROPOSED` when the two obligations share a `:Document`
and `IMPLEMENTS_PROPOSED` when they do not. Knowable at the only moment both sides are in hand,
so nothing downstream has to infer it from section names or version ids.

`propose_links` still writes no promoted edge of any kind. Its module docstring's guarantee —
that nothing in it can write `IMPLEMENTS` — extends unchanged to the pairing side.

### 3. The diff consults confirmed pairings before its section rule

This is the load-bearing change and the smallest one. `diff_versions` keeps every existing step.
Before the section-based `MODIFIED` rule runs, any pair of still-unmatched obligations carrying a
`PairingDecision{verdict: 'paired'}` is emitted as `MODIFIED` regardless of section path.
Everything unconfirmed falls through to ADR-031's rule exactly as today.

Human input therefore takes precedence over the heuristic rather than competing with it, and the
heuristic is not weakened — the ambiguous-section fallback still refuses to guess. What changes is
that a reviewer can now settle the cases it refuses.

A `distinct` verdict is not merely the absence of `paired`: it suppresses the section rule for
that pair, so a reviewer can say "these two sit in matching sections and are nevertheless
different clauses" and have it stick.

### 4. Durability is ADR-027's problem, already solved

`:PairingDecision` is canonical and survives every drop, as `:LinkDecision` does. Obligation ids
hash their version (ADR-013), so re-extracting either edition rehashes them and strands pairings
in exactly the way ADR-027 describes for link decisions. `repoint_decisions` already captures
statements before the drop and repoints by them; pairings reuse that machinery rather than growing
a second copy of it, and the counts a rebuild reports gain `pairings_repointed` and
`pairings_unpairable` beside their existing siblings.

### 5. A surface of its own

Decided in review on 2026-09-09: pairing gets its own queue and screen rather than sharing
Review's.

- `GET /pairings/queue?from_version_id=&to_version_id=` — the clauses the diff left unpaired
  between those two editions (its `ADDED` on the newer side, its `REMOVED` on the older) and the
  `PAIRING_PROPOSED` edges between them, bounded and reporting its own backlog the way the review
  queue now does.
- `POST /pairings/{from_obligation_id}/{to_obligation_id}` — a verdict, actor from the
  authenticated principal.

Scoped to an edition pair because that is the unit of the work: a reviewer pairing a reissue is
working through one document's restructure, not a global list. The screen shows both editions'
unpaired clauses so the reviewer can see what is left, which the review queue's one-proposal-at-a-
time shape cannot express.

### 6. What else moves

- The build screen's *Propose links against* fieldset stops offering this document's own editions
  as link candidates and offers other documents' editions instead. Same-document editions are
  routed to pairing, which is where they belong.
- `TriageCitationOut` gains `version_id`, for the reason Review's citation just did: a citation
  naming only the document settles nothing when two editions of it are in play.

## Migration

**The 119 `IMPLEMENTS_PROPOSED` between same-document editions are derived and regenerate on the
next rebuild.** Dropping them costs nothing and a rebuild re-proposes them as `PAIRING_PROPOSED`.

**The one same-document `:LinkDecision` is canonical and must not be discarded.** It was recorded
during the walkthrough on 2026-09-09 and approved a `newer → older` pair within DoDD 5000.01,
which under this design is a pairing rather than a link. It migrates to a `:PairingDecision` with
verdict `paired`, carrying its actor, rationale and timestamp. ADR-014 says no rebuild may discard
a decision; a schema change is not an exception, and the same rule is why this is a migration
rather than a delete.

The second existing decision is already `unpromotable` — its source obligation no longer exists —
and is cross-document by construction. It stays a `:LinkDecision` and continues to be counted as
unpromotable.

## Testing

Every claim above that the code has to keep is a test, not a comment:

- A same-document candidate produces `PAIRING_PROPOSED` and never `IMPLEMENTS_PROPOSED`, and a
  cross-document one the reverse.
- A confirmed pairing across **different** section paths yields one `MODIFIED` rather than an
  `ADDED` and a `REMOVED` — the restructure case, which is the whole point and which the section
  rule cannot produce.
- A `distinct` verdict suppresses a `MODIFIED` the section rule would otherwise have made.
- A pairing survives a rebuild that rehashes both editions' obligation ids, and an unpairable one
  is reported rather than dropped silently.
- Triage, given a cross-document `IMPLEMENTS` over a confirmed pairing, returns a row with the
  correct `previous_statement` — the end-to-end claim, and the one that fails today.

Each is mutation-checked: the walkthrough that produced this document also found two tests whose
names promised guarantees their bodies did not make, and both had passed for months.

## Consequences

**Makes easy.** The two questions become separable, so each screen asks one. A restructured
reissue becomes pairable at all, which it is not today. Triage becomes reachable from the work a
reviewer actually does, which is the defect this started from.

**Makes hard.** There are now two canonical decision types and two replay paths, and a future
third would be a signal to generalise rather than to add. The pairing queue is a second surface
with its own emptiness states to explain honestly, and the project's standard for that is high.

**Commits us to.** Pairing being a human judgement. The lexical proposer may suggest and the
section rule may infer, but neither settles a pairing that the other got wrong — which is the same
position ADR-032 took for merging two documents, for the same reason.
