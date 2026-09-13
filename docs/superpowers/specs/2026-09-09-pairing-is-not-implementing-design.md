# Settling the pairs the diff declines

**Status:** Design (rev. 8, implemented) · **Date:** 2026-09-09, revs. 5-7 on 2026-09-10,
rev. 8 on 2026-09-12 ·
**Sprint:** — (found in sprint 12's walkthrough of the review queue against live proposals,
`docs/backlog/backlog.md:180-188`)

> **Revisions 1 and 2 were both wrong about the code, and both passed the author's own review.**
> Rev. 1 said `changes/diff.py` pairs only by section; `_pair_by_wording` had done cross-section
> wording matching all along. Rev. 2 said a same-document `IMPLEMENTS` was unreachable by Triage;
> it was in fact producing a top-scored row asserting that a document implements itself. An
> adversarial subagent found the second error and thirteen more (standing rules 6 and 7 exist
> because of this). Rev. 3 was written against the code with `file:line` for every claim — and the
> adversarial check still found four structural errors: an outcome with no line to observe it
> from, an outcome contained in another, §2 contradicting §3 on who writes the edge, and §8
> asserting the opposite of the problem section. Rev. 4 fixed those; its own refutation round
> returned another crop, this time in the design rather than the citations: a `paired` verdict
> that lost to the section rule the Consequences said it outranked, a counter reported on a path
> that never runs, settled pairs no reviewer could reach again, and a migration that stranded
> every live proposal. Rev. 5's check returned seven more, each narrower and deeper: a mechanism
> asserted "by construction" without saying what construction, a second way a verdict could be
> silently outranked, direction unpinned at the very API boundary the queue is built on, and an
> export "pattern to extend" that was itself a live bug — the export read properties nothing
> writes, so every real verdict exported with a null key, no timestamp, and no rationale. That
> bug is fixed in code with this revision, not filed. Rev. 6's plan-gate check verified every
> citation clean and dry-ran the test fixtures, then found five material errors anyway — all in
> the Migration and §7, the two sections written last and attacked least: a justification that
> contradicted §3, a retired verdict `PROMOTE` would resurrect forever, a conflict the migration
> could mint that the 409 could not refuse, a deliverable with no vehicle, and a sentence
> requiring facts that never cross the interface. Each revision's errors were invisible to the
> mind that made them; rev. 7 resolves the lot, and the implementation plan is written against
> this revision.
>
> **Rev. 8 is written from the shipped code, and records four things implementation discovered
> that rev. 7 could not have known.** Three are mechanisms the code grew and this document did
> not: the `:PairingLock` and the race it closes (§4, §6 — the only undiscoverable mechanism on the
> feature, since removing it keeps the whole non-integration suite green), `PROMOTE`'s document
> predicate (§8), and the queue's `outcome` filter, without which the page cap made the declines
> this design exists to settle unreachable on any substantially reworded edition pair (§6). The
> fourth is two shapes measurement corrected: `PairingSettledOut` is not two ids, and
> `pairing_decisions_stranded` is not "the true analogue of `unpromotable`" (§3, §6). Sections
> amended in place, each saying it was written during implementation and why.

## What has already been fixed

The live defect is closed, separately from this design. `changes/propagate.py`'s traversal had no
document predicate, so a same-document `IMPLEMENTS` and a change in that document met and produced
a row claiming DoDD 5000.01 implements DoDD 5000.01 — scored 12.0, `KIND_WEIGHT["REMOVED"]` at 3.0
times `MODALITY_WEIGHT` at 4.0, the top of the range `score` can return (`propagate.py:76-80`,
`180-182`), with a null `previous_statement`. `WHERE document <> higher_document` now guards the
row query (`propagate.py:83`), and `COUNT_CHANGES` repeats *every* condition the row query
imposes, not only that one: the documents must differ **and** both citations must be buildable —
`primary_anchor`'s `CALL` is an inner join, so a count matching only on `:MANDATES` would disagree
with the rows over any obligation lacking an `:ANCHORED_IN` chunk (`propagate.py:121-135`). A
same-document change is therefore counted as unlinked rather than vanishing from `rows` and
`unlinked_changes` alike.

This document is the remaining gap, which is a capability rather than a defect.

## The problem

Between two editions of one instrument the diff pairs what it can and **declines the rest**, and a
declined pair has no route to a human. `_plan_changes` (`diff.py:186`) runs four passes:

1. Exact match on `(section_path, normalized statement)` (`diff.py:189-190`).
2. The section rule — one unmatched clause each side in a section is `MODIFIED` (`diff.py:203-222`).
3. `_pair_by_wording` (`diff.py:108`, called at `diff.py:233`) — everything left, scored across
   sections with `links/propose.py`'s `score_pair`.
4. Survivors become `ADDED`/`REMOVED` (`diff.py:242-274`).

Pass 3 refuses pairs at **two different places, and they are not alike**. The greedy loop declines
through two branches: partner already consumed by a higher-scoring pair (`diff.py:155`), and within
`PAIRING_MARGIN = 0.05` of a rival (`diff.py:161`). But a pair below `PAIRING_CONFIDENCE = 0.75`
never reaches that loop at all — it is discarded at the scoring filter (`diff.py:132`) and enters
no data structure: not `scored`, not the sort, not `_best_elsewhere`. It exists only for the
duration of a `score_pair` return value. A fourth exclusion is silent — `score_pair` returns
`None` when either statement has no content words (`propose.py:61-62`) or below
`MIN_CONFIDENCE = 0.30` (`propose.py:69-70`), so those pairs are never scored at all. That silent
class contains the case a human most obviously beats the measure: a complete rewording sharing no
content words. §6's route must therefore not depend on an edge having been recorded.

The margin rule is narrower than it looks: `_best_elsewhere` (`diff.py:143-152`) scans only
`scored`, which holds pairs already ≥0.75, so a 0.76 pair with a 0.74 rival is auto-paired
uncontested — and `_best_elsewhere` has no confidence filter of its own, so that property is
inherited entirely from the `diff.py:132` gate. It also counts rivals whose obligations a higher
pair has already taken, which has a consequence §2 must honour: the pair that consumed a partner
scores at least as high and shares an endpoint, so **every pair declined at `diff.py:155` also
satisfies the margin predicate**. The two decline branches are a precedence chain, not disjoint
conditions.

Every one of those refusals is deliberate — ADR-031: *"If two candidates score within a hair of
each other, both stay `ADDED`/`REMOVED` and the summary says so"* — and correct. What is missing
is that a person who can tell them apart has no way to say so. Measured on
`dodd-5000-01@2018-08-31` → `dodd-5000-01@2022-07-28`: 17 `MODIFIED`, 66 `REMOVED`, 57 `ADDED` — a
dev-graph observation of 2026-09-09, not a repository fact, like the counts in Migration. (ADR-031
reports 0/80/11 for the 2018→2020 pair, but measured under section-only pairing before the wording
pass it introduced existed, so the two sets differ by pipeline as well as by pair and are not
quotable side by side.)

Meanwhile `propose_links` re-scores those same pairs at `MIN_CONFIDENCE = 0.30` with no margin
rule (`propose.py:69-70`) and files them as `IMPLEMENTS_PROPOSED` — a relationship that means
something else. The build screen can only offer this document's own editions as candidates
(`frontend/src/views/DocumentDetail.tsx:379-396`), so that is what the UI produces.

## Decision

**Same-document pairing belongs to the diff. A person settles what the diff declines, and what it
guessed. `IMPLEMENTS` becomes cross-document only.**

### 1. `propose_links` skips pairs inside one document

`READ_OBLIGATIONS` (`propose.py:94-98`) filters to the named version ids but returns bare
`id`/`statement` rows that identify neither the owning document nor which version they came from
(`propose.py:97`), so it gains the owning document and both call sites at `propose.py:124-125`
change shape. A pair whose obligations share a `:Document` is skipped.

This is *not* the same as the existing self-candidate skip (`propose.py:131-135`), whose stated
reason is narrower — a version named as its own candidate scoring 1.0 against itself — and the
comment must not be reused.

**`WHY_EMPTY` breaks unless it changes with this.** `routers/review.py:92-100` defines
`documents_comparable` as documents with two editions holding obligations, and `models.py:221-244`
documents it as what separates "caught up" from "nothing could be here yet". After §1 that is
exactly the configuration which can no longer yield a proposal, so it becomes the false all-clear
STORY-090 added it to prevent. The replacement must be computable, so here it is: **count distinct
documents holding at least one obligation in any edition; a proposal is impossible below 2.**
Necessary and not sufficient: two documents that hold obligations may still yield nothing, because
`score_pair` must clear `MIN_CONFIDENCE` and the caller must name the candidate editions. The
screen branches on the direction that holds. The field is renamed with its meaning — `documents_comparable` described the
edition-to-edition question this design retires. Six sites, because the field is user-facing and
mirrored: `WHY_EMPTY` itself, the `models.py:221-244` docstring, the frontend type declaration
(`types.ts:156` — renamed on one side only, TypeScript still compiles against the stale
declaration, the runtime field is `undefined`, `undefined === 0` is false, and the empty state
falls through to "Nothing is waiting for review", the exact false all-clear this field exists to
prevent), the backend assertions (`test_review.py:268, 284, 314`), and the Review screen's empty
state, whose current advice — *"Build a second edition of a document that already has one"*
(`Review.tsx:158-164`) — becomes precisely the action that can no longer produce a proposal, with
a test pinning that wording that must change with it.

### 2. What the wording pass decided becomes a record the diff writes

The wording pass *produces* candidate records; `diff_versions` *persists* them — the split the
module already enforces for `:Change` (`_plan_changes` plans at `diff.py:308`, `WRITE_CHANGES`
writes at `diff.py:314-322`), and the one §3 depends on. `_pair_by_wording` appends to a
`candidates` accumulator threaded in beside `changes` (`diff.py:108-114`), each record carrying
both obligation ids, `confidence`, `rationale`, and `outcome`; `_plan_changes` returns them beside
the changes, and `diff_versions` writes `(:Obligation)-[:PAIRING_CANDIDATE]->(:Obligation)`,
from-side→to-side, via a `WRITE_CANDIDATES` statement next to `WRITE_CHANGES`. `diff_versions`
has no notion of chronology — it binds whatever from/to the caller passes (`diff.py:290-291`),
and Triage validates existence only (`triage.py:35-45`) — so "older→newer" is not a property this
layer can promise; §6 pins it at the one route built on these edges.

`outcome` is **the first rule that fired, in code order** — not four disjoint predicates:

- `auto_paired` — the greedy loop made the pair (`diff.py:166-183`).
- `partner_taken` — declined at `diff.py:155`: an obligation already consumed by a higher-scoring
  pair earlier in this loop.
- `contested` — declined by the margin rule at `diff.py:161`.
- `below_threshold` — never entered the loop. Scored in [`MIN_CONFIDENCE`, `PAIRING_CONFIDENCE`)
  and discarded today at the false arm of `diff.py:132`, which is where it is captured. It is not
  a branch of the decline loop, and no test can reach it there.

A pair `score_pair` never scores carries no outcome by design; its route to a human is §6's POST,
which does not require a recorded edge.

**`partner_taken` is contained in `contested`, and the spec says so rather than pretending
otherwise.** The consuming pair remains in `scored` at a confidence at least as high, shares an
endpoint, and `_best_elsewhere` counts it — so the margin predicate holds for every partner-taken
pair, and the labels are distinguished by precedence, not by condition. `partner_taken` stays a
separate label because it is the actionable one: an `auto_paired` winner exists on the taken side.
**Both sides can be taken** — declined when *either* endpoint is consumed (`diff.py:155`), so up
to two winners exist, and the queue names each side's taker. The join must be scoped, because one
obligation serves every diff its edition is in (a middle edition belongs to two pairs, and Triage
accepts arbitrary version ids): winner = the `auto_paired` edge sharing this pair's endpoint
**whose other endpoint is `:MANDATES`-ed by the request's other edition** — direction alone cannot
separate two diffs from the same older edition.

**Pass-3 pairing structure is identical before and after this change**: which pairs are made and
declined, at which confidences. `scored`, `_best_elsewhere` and the greedy loop stay restricted to
≥ `PAIRING_CONFIDENCE`. Widening `scored` down to `MIN_CONFIDENCE` would silently change
behaviour — `_best_elsewhere` has no confidence filter of its own, so a 0.78 pair with a 0.74
rival auto-pairs today and would become contested — and would let 0.30-confidence pairs reach the
pairing append. The sub-threshold capture is a separate accumulator at the scoring filter, and a
mutation test guards the invariant (§ Testing). The invariant is deliberately structure, not
bytes: §7 rewrites the rationale that `diff.py:176-181` embeds in every wording-pass summary, so
summaries change while pairings do not.

**Bounded, because the scoring loop is a cross product** (`diff.py:125-131`) — and it runs before
pass 3 consumes anything, so on the measured pair it is at least 66 × 57 ≈ 3,800 `score_pair`
calls and up to (66+k) × (57+k) ≈ 6,100 if all k = 17 `MODIFIED` came from the wording pass;
re-run on every Triage GET. Everything ≥ `PAIRING_CONFIDENCE` is recorded unconditionally. Below
it, the rule is applied **after** the greedy loop, over the sub-threshold accumulator: a record is
kept iff at least one of its endpoints finished the loop unpaired, and it is that endpoint's
best-scoring sub-threshold candidate or within `PAIRING_MARGIN` of that best. "Best" ranges over
sub-threshold candidates only — pairs ≥ `PAIRING_CONFIDENCE` are recorded on their own and do not
suppress a declined clause's nearest miss. Timing matters and is pinned by a test: an
`auto_paired` clause's 0.60 candidate is kept only if its *other* endpoint finished unpaired and
it is that endpoint's best. Recording the full cross product would write thousands of edges per
edition pair per GET and bury the one candidate worth a look under its own long tail.

**Recording `auto_paired` too is the point.** Rev. 2 recorded only refusals, which left no route to
the one case ADR-031 names as the real risk: a `MODIFIED` the rule produced and got wrong. A
reviewer must be able to reach a pairing to *undo* it, not only to make one.

**It needs its own drop, and the key must bind both editions.** `drop_changes` runs `DETACH
DELETE` on `:Change` nodes (`diff.py:52-55`, `DROP_PAIR` at `diff.py:46-50`); an edge between two
`:Obligation` nodes hangs off no `:Change` and is unreachable from either. On the rebuild path the
edges happen to vanish via `drop_obligations`' own `DETACH DELETE` (`obligations.py:100-103`,
called one line after `drop_changes` at `links/rebuild.py:116-117`) — by accident, from a
different statement, and not at all on the re-diff path. `DROP_PAIR`'s scoping mechanism does not
transfer — it scopes through the `:Change` node's `FROM_VERSION`/`TO_VERSION`, which a bare
relationship cannot carry — and "any edge touching either edition's obligations" is wrong: a
middle edition's obligations belong to two pairs, and that reading deletes the neighbouring
diff's candidates. So the statement is written out:

```
MATCH (:DocumentVersion {version_id: $from_version_id})-[:MANDATES]->(:Obligation)
      -[r:PAIRING_CANDIDATE]-
      (:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $to_version_id})
DELETE r
```

— **undirected on the candidate edge**, deliberately: a Triage GET run with the pair reversed
writes its edges the other way, and a directional drop would leave those orphaned forever while
deleting only the well-oriented ones. Called from `diff_versions` where `DROP_PAIR` already is
(`diff.py:303-306`), returning a **relationship** count, not `nodes_deleted` (compare
`diff.py:286-287`), with a test that re-diffing one pair leaves an adjacent pair's candidates
intact.

### 3. Decisions are threaded in, not fetched

`_plan_changes` takes two dicts and no `tx`, and its docstring says why — *"so the rule is testable
on its own"* (`diff.py:186-188`); `_pair_by_wording` likewise takes no `tx` (`diff.py:108-114`),
though only its signature says so. Both keep that property. `_plan_changes`'s shape changes to
carry §2's outcomes and the verdicts' fates up — it returns candidates and counts beside the
changes, because `diff_versions` calls `_plan_changes` (`diff.py:308`), never `_pair_by_wording`
(`diff.py:233-235`). `diff_versions` reads the decisions — **scoped through `:MANDATES` to the
two named editions**, exactly as §3's settled-pairs read is, so a middle edition's verdict cannot
leak into a neighbouring pair's diff — and passes a `dict[(old_id, new_id)] -> verdict` down,
**looked up under both orientations**: the record's canonical direction is §6's business, and a
verdict must apply however the ids fall out of a given run.

**A `paired` decision is applied between pass 1 and the section grouping, and "consumed" means
deleted, not marked.** Pass 2 pairs unconditionally (`diff.py:203-222`) and runs before pass 3,
so applying `paired` inside `_pair_by_wording` — where rev. 4 put it — let a structural heuristic
consume a human verdict's obligation and shelve the verdict, the exact outranking the
Consequences forbid. And "before the section rule" alone is not enough, because pass 2 never
reads `paired_old`/`paired_new` — it reads only the `by_section` dicts built from the unmatched
sets at `diff.py:192-197`. So the mechanism is stated, since two placements satisfy the prose and
one is wrong: the decision's obligations are **deleted from `unmatched_old`/`unmatched_new`
after they are computed (`diff.py:189-190`) and before the `by_section` grouping is built
(`diff.py:192`)**, with the `MODIFIED` emitted there. Marking via the paired sets is
insufficient; deletion also means a settled clause no longer counts toward a section's
`_ambiguous` tally (`diff.py:237-240`), which would otherwise report a human-settled clause as
ambiguity. `paired` then wins against pass 2 and pass 3 because neither ever sees its clauses. **Pass 2 must also honour `distinct`** — the section
rule would otherwise re-pair a `distinct` pair alone in a section — and a `distinct` pair is
removed from pass 3's `scored` entirely **and from §2's sub-threshold accumulator**, which a pair
under `PAIRING_CONFIDENCE` reaches without ever touching `scored`. Removed from the bound's
"best" as well as from recording: the reviewer said *not this one*, so its score must not shadow
the endpoint's next-best live candidate. Pass 1 is the one thing left that can pre-empt a
verdict, and legitimately: an identical clause persisting in both editions is a fact, not a
pairing judgement. A `paired` decision naming an obligation pass 1 matched — the clause exists
unchanged in the other edition, so the "reworded" claim has nothing to attach to — cannot be
applied, and is counted, never dropped. Two live `paired` decisions sharing an endpoint would be
a second pre-emption path — the diff's model is one-to-one (`diff.py:166-183`), so one verdict
would silently shelve the other, decided by dict iteration order — and the design forbids the
state instead of arbitrating it: §6's POST rejects it at the source, so the diff never meets it.

**The count lives where the diff runs, because the rebuild never runs it.** Rev. 4 sent
`pairings_unapplied` to "the rebuild's counts", but pass-1 conflicts are discovered inside
`_plan_changes`, which only `diff_versions` calls, whose only non-test callers are the Triage GET
(`routers/triage.py:96`) and §6's queue — and the rebuild deliberately does not re-run the diff
(`rebuild.py:107-108`). So `pairings_unapplied` is returned by `diff_versions` beside the kind
counts and surfaced in both GET responses. The rebuild-side loss is a different event with a
different name: **`pairing_decisions_stranded`** — a `:PairingDecision` the diff can no longer
apply, because an obligation it names is gone or no longer `:MANDATES`-ed by an edition — counted
by a query beside it and reported in the rebuild's counts, as `rejections_stranded` already is.

**One count, not two, and it is the analogue of `unpromotable` *and* `rejections_stranded`
together.** Corrected during implementation: the link side splits its two because the losses differ
in consequence — a stranded approval leaves a link missing and the proposal returns to the queue,
while a stranded rejection leaves a suppression nobody is applying and the reviewer is never told
they already refused it. A stranded `paired` and a stranded `distinct` do not differ that way:
either way the clause the verdict named is gone and the pair is re-asked from scratch. So the query
filters no verdict, and a reader splitting it into two would be splitting on a distinction this
vocabulary does not have (`links/pairing.py`, ADR-027).

A decision-settled pair is not re-recorded as a candidate — the `:PairingDecision` is the record,
and a candidate edge re-asking a settled question would put it back in the queue. Settled pairs
stay reachable through §6: the queue returns them, marked settled, read from `:PairingDecision`
joined through `:MANDATES` to the two named editions.

### 4. `:PairingDecision` — canonical, its own vocabulary, its own constraint

| | Pairing | Implements |
| --- | --- | --- |
| Question | is the newer clause the reworded older one? | does our clause discharge that duty? |
| Scope | one document, two editions | two documents |
| Node | `:PairingDecision` | `:LinkDecision` (unchanged) |
| Verdict | `paired` / `distinct` | `approve` / `reject` |
| Effect | pairs or unpairs in the diff | promotes `IMPLEMENTS` |

Direction is older→newer — a property §6 enforces at the route, since neither `diff_versions` nor
`:Change`'s `FROM_VERSION`/`TO_VERSION` carries chronology; they carry request order. An
obligation pair *determines* its edition pair (`obligation_id` hashes its `version_id`,
`extraction/schema.py:314-316`, so each obligation belongs to exactly one edition), which is what
lets the route order the two ends before recording. The properties are **`old_obligation_id` /
`new_obligation_id`** — `source`/`target` is `:LinkDecision`'s vocabulary and answers the other
question — plus `verdict`, `actor`, `rationale`, `at`, and `key`. `key` is a *directional* hash
of both obligation ids in that order, as `:LinkDecision`'s is (`decisions.py:31-39`,
`decision_key` at `decisions.py:225-236`), and **`db.py` gains `pairing_decision_key_unique`**
beside `link_decision_key_unique` (`db.py:57-60`) — §5's collision handling depends on that
constraint existing.

`db.py` gains a second constraint, **`pairing_lock_key_unique`**, for the `:PairingLock` node §6's
409 is built on. It is not bookkeeping: a bare `MERGE` under concurrency can create two nodes for
one key, and two transactions locking two different nodes is the race the lock exists to close.
§6 states the mechanism. The lock node carries `key`, `edition_pair` and `at`, is never read back,
and is derived — nothing is lost if one is deleted between verdicts.

### 5. Durability — a refactor, not a reuse

Rev. 2 claimed `repoint_decisions` could simply be reused. It cannot: it is bound to
`:LinkDecision` at `decisions.py:106`, `115`, and `124`, hardcodes `source_obligation_id` /
`target_obligation_id` at `decisions.py:107-110` and `116-117`, and calls `decision_key` directly
at `decisions.py:190`; its in-batch collision rule exists to protect `link_decision_key_unique`
(`decisions.py:204-218`). Reuse means parameterising label, property names, key function and
constraint — a refactor of the canonical decision path, and it is in scope here rather than
assumed away.

Rev. 2 also overstated the hazard. `obligation_id` hashes `version_id | section_path |
normalize(statement)` (`extraction/schema.py:314-316`), so re-extracting an edition leaves ids
stable **unless the section path or the wording moved** — ADR-027's actual scope.
`pairing_decisions_stranded` (§3's rebuild-side count) is non-zero only in that case;
`pairings_unapplied` is the diff-side count and has its own cause.

The statements are captured by `read_obligation_statements` from `links/rebuild.py:114`, not by
`repoint_decisions`.

### 6. The pairing route runs the diff itself

`diff_versions` has exactly one caller outside the tests — the Triage GET handler
(`routers/triage.py:96`). A queue reading edges written from inside the diff would be empty for any
edition pair nobody had opened in Triage, and a verdict would take effect only next time someone
loaded that screen.

So `GET /pairings/queue?from_version_id=&to_version_id=` calls `diff_versions` itself, exactly as
Triage does, then returns the candidates, the settled pairs (§3), and `pairings_unapplied`. It
inherits the same "a GET writes derived nodes" trade that `routers/triage.py:66-69` already flags
and accepts. **It also pins direction, because nothing beneath it does**: a from/to pair that is
not older→newer by the corpus's own ordering — `coalesce(effective_date, '')` then `ingested_at`
(`documents.py:255`), with `version_id` as the final tie-breaker this route adds, since two
undated editions ingested in one instant otherwise tie and neither orientation would pass — is a
400, not a reversed diff quietly writing reversed edges and serving a reviewer a queue whose
question is upside down. The POST is not the protection here — it orders whatever it is given —
the 400 protects the queue and the graph. Triage keeps its arbitrary-direction behaviour; its
reversed runs' edges are cleaned by §2's undirected drop and its verdicts still apply through
§3's orientation-normalized lookup.

**The page is capped, and the cap cuts declines first, so the queue takes an `outcome` filter.**
Written during implementation, because the whole-branch review proved the screen could not reach the
pairs it exists to settle. Everything at or above `PAIRING_CONFIDENCE` is recorded unconditionally
(§2), and a declined pair is by construction at or below the confidence of whatever beat it —
`partner_taken` never outscores the winner that consumed its endpoint, `contested` sits within
`PAIRING_MARGIN` of its rival, `below_threshold` is under the bar entirely — so a page ordered by
confidence and capped at 50 holds nothing but pairings the diff already made. Measured live on a
61-clause edition pair: 50 rows, every one `auto_paired`, the single decline reachable only past the
page. `outcome` narrows the page to one of §2's four labels, validated against the labels the diff
writes so the two cannot drift, and an unrecognised one is a 400 rather than an empty page — an empty
queue is an answer, and a typo must not be able to give it. `pending_by_outcome` reports the whole
backlog per label beside it, because a filter nobody knows to apply is not a route to anything. The
cap itself stays: what a class with more members than the cap needs is a bound on above-bar
*recording*, which §2 deliberately does not have.

`POST /pairings/{old_obligation_id}/{new_obligation_id}` records a verdict, actor from the
authenticated principal. **Admissibility is membership, not a recorded edge**: the two obligations
must exist and be `:MANDATES`-ed by two editions of one document; 404 otherwise, and the route
orders the pair older→newer itself before keying (§4) — the obligation ids determine the
editions, the editions order. This deliberately departs from the proposal-gated rule at
`routers/review.py:195-202` — a link verdict needs a proposal, but the pairing question exists
for every pair of clauses in the two editions, and gating on a candidate edge would make the
recorder outrank the person for exactly the declines the problem section enumerates: the silent
`score_pair` exclusions and the sub-threshold pairs §2's bound drops. A `distinct` verdict on a
pair §3 stopped recording stays reversible for the same reason. **One conflict is refused rather
than recorded, and it is scoped to the edition pair**: a `paired` verdict naming an obligation
that already carries a live `paired` verdict with a different partner **in the same other
edition** is a 409 telling the reviewer which pairing to mark `distinct` first — the diff is
one-to-one, and two live `paired` verdicts on one clause within one pair is a state whose loser
would be chosen by iteration order (§3). The scope matters: a middle edition's clause
legitimately pairs into both adjacent pairs — B paired to its A-predecessor *and* to its
C-successor — which is the very case §3's `:MANDATES`-scoped read exists to keep separate, and an
unscoped 409 would refuse the second verdict and prescribe destroying the first.

**The 409 alone does not hold, and a lock is what makes it hold.** Written during
implementation, because a Critical reproduced the race six times out of six against the version
above. Neo4j is read-committed and takes no locks for reads, and two verdicts on one clause
`MERGE` two *different* `:PairingDecision` nodes — so putting the conflict read in the same
transaction as the write serialises nothing: there is no node either transaction blocks on, both
reads come back empty, both commit, and the graph holds two live `paired` verdicts on one clause,
with the loser chosen by dict iteration order on the next diff (§3). Re-reading after the write
does not help either; both transactions stay blind to the other's uncommitted writes until commit.
So the route takes a write lock *before* the conflict read and in the same transaction as the
record: `MERGE (:PairingLock {key: …})` plus a `SET`, keyed on the **edition pair** in canonical
older→newer order so every caller settling a pair between those two editions takes the same lock.
Three parts are each load-bearing. The `SET`, because a `MERGE` that matches need not take an
exclusive lock on what it found, and without a write the second transaction sails past.
§4's `pairing_lock_key_unique`, because a bare `MERGE` under concurrency can create two nodes for
one key. And the scope being the edition pair rather than the clause: a single lock cannot
deadlock, where a lock per (clause, other edition) would need a total acquisition order to be sure
of it — the cost is that two reviewers settling unrelated pairs between the same two editions
serialise, which on a human-driven review screen is not a cost worth a deadlock argument.

Deliverables at the same granularity §8 demands elsewhere: `routers/pairings.py`, registered in
`main.py:165-172` beside the seven existing routers (eight registrations now, this one included); in `models.py` beside their review analogues
(`models.py:213-257`): `PairingCandidateOut` — `old` and `new` sides as `ObligationCitationOut`,
`confidence`, `rationale`, `outcome`, and `taken_by`, a list of zero to two obligation ids naming
the `auto_paired` winners' other ends via §2's `:MANDATES`-scoped join; `PairingSettledOut` —
**both full `ObligationCitationOut` sides** plus `verdict`, `actor` and `rationale`, each addition
because the shape measured here was wrong. Ids alone leave the screen nothing to draw in precisely
the case the list is full: a settled pair is never also a candidate, so two `distinct` verdicts
between one edition pair give `settled=2, items=0` and no row to borrow the statements from. And a
settled model without `rationale` makes the undo button post an empty reason — `RECORD` SETs
`rationale` unconditionally — erasing the justification of the verdict being reversed, unseen.
`PairingQueueOut` — `items`, `settled`, `pairings_unapplied`, `pending` on the review queue's own
pattern (`models.py:239-244`), and **`pending_by_outcome`**, the backlog split by label: a declined
pair scores at or below whatever beat it, so a confidence-ordered page cuts declines first, and the
breakdown is what tells a reviewer a class exists before they filter to it;
`PairingVerdictIn` — `verdict` and `rationale`, no actor, for `VerdictIn`'s reason
(`models.py:247-257`). The screen is `frontend/src/views/Pairings.tsx` with a `routes.tsx` entry
and `client.ts` functions — a deliverable, not a knock-on. Bounded and reporting its own backlog,
as the review queue now does (STORY-113 — a backlog entry, not a story file:
`docs/backlog/backlog.md:180-192`).

### 7. The rationale must be rewritten for this reviewer

`_rationale` ends *"Confirm the org clause actually discharges the higher duty before approving."*
(`propose.py:87-91`). That sentence does not wait for the new screen: the wording pass embeds it
verbatim in every pass-3 `MODIFIED` summary (`diff.py:176-181`), which is persisted on the
`:Change` (`diff.py:66-68`) and shown on Triage today. So `diff.py:176-181` is a named change
site, not just the future pairing screen: pairing needs its own sentence — what the two clauses
share, which branch declined them, and that the question is whether one is the other reworded —
and §2's invariant is scoped to pairing structure precisely so this rewrite can land.

The facts that sentence needs never cross the interface today: `shared_words`,
`shared_designators` and `overlap` exist only inside `_rationale` (`propose.py:78-91`), and
`Candidate` carries the finished string, advisory included (`propose.py:35-38`). So this is a
shape change, named as one: the measurement splits from the sentence, and `propose.py` gains
**`score_pairing(after_statement, before_statement) -> Candidate | None`** — same measure, same
floor, pairing-worded sentence — which `_pair_by_wording` calls in place of `score_pair`, for
both the summary and the recorded candidate `rationale`. `propose_links` keeps `score_pair` and
its wording verbatim; the review queue's persisted proposal rationale must not change.

### 8. Knock-ons

- The build fieldset (`DocumentDetail.tsx:379-396`) offers **only this document's own editions** —
  `versions` comes from `GET /documents/{slug}/versions` (`DocumentDetail.tsx:87-92`,
  `documents.py:239-256`) and the filter excludes only the *selected* edition. The rebuild *API* is
  already broader: candidates are validated by version id alone, no slug (`rebuilds.py:35-38`,
  `115-127`), and `propose_links` binds no document (`propose.py:94-98`) — so other documents'
  editions can be named by a direct API call today, just never by this screen. After §1 the
  same-document candidates this fieldset offers can no longer yield a proposal, so cross-document
  `IMPLEMENTS` needs the fieldset to offer other documents' editions — a UI change this design
  names as in scope, not a knock-on to discover later.
- `TriageCitationOut` gains `version_id` — five sites in three backend files, plus the frontend
  type: `models.py:260-269`; `changes/propagate.py` three times (the `TRIAGE` query returns no
  version id despite binding `our_version`/`higher_version` — bindings at 65 and 67, `RETURN` at
  84-99 — the `TriageRow` dataclass at 140-158, and the `TriageRow` construction inside
  `triage()` at 196-214, a frozen dataclass with no defaults, so a new required field is a
  `TypeError` there before it is anything else); `routers/triage.py:131-144`, whose constructors
  fail validation the moment the model gains a required field; and `frontend/src/api/types.ts` if
  the field is shown, which is the point of adding it.
- `PROMOTE` (`decisions.py:43-49`) has no document predicate, so §1 makes `IMPLEMENTS`
  cross-document only for *new* proposals, transitively via the 404 at `review.py:195-202`. The
  `propagate.py` guard already shipped means a stray same-document edge can no longer produce a
  Triage row, but enforcement belongs at `record_decision` **and at `PROMOTE`**. Written during
  implementation, because the recorder alone is a rule about verdicts recorded since rather than
  about the graph: a legacy same-document `approve` whose obligation node is absent when the
  Migration runs matches neither its conversion query nor its census — both open by matching both
  obligations — and when a rebuild re-extracts the clause under the same content-derived id, the
  next replay promotes the edge. `PROMOTE` is the only writer of `IMPLEMENTS` anywhere, so the
  predicate belongs there for the same reason §1's belongs in `propose_links`. Phrased as "one
  document holds both" and negated, never as "I cannot see two documents": a verdict one side of
  which a re-extraction stranded resolves to no document at all, and the second phrasing would
  refuse every legitimate cross-document promotion the moment one clause moved.
- **The export must carry the new canonical node or Reset destroys it.** The decisions category
  matches only `:LinkDecision` (`export.py`); `/admin/reset` runs `MATCH (n) DETACH DELETE n` and
  the Reset screen tells the user the export is their only copy. A `:PairingDecision` left out of
  the export is a human verdict destroyed by a screen that promised a copy. The existing category
  was not a template to copy: it read `decision.decision_key` and `decision.decided_at` —
  properties nothing writes; `record_decision` writes `key` and `at` — and omitted `rationale`
  entirely, so every verdict recorded through the real path exported with a null key, no
  timestamp, and no rationale, while its test CREATEd a node carrying the export's own column
  names and asserted them back. **That defect is fixed with this audit** (export now reads
  `key`/`actor`/`rationale`/`at` as written, and the test records through `record_decision`); the
  `:PairingDecision` category is exported as **`pairing_decisions`**, specified by the same
  fields §4 names — both obligation ids, verdict, actor, rationale, timestamp — and the Reset
  copy names it.
- **The `decisions` category widens to `:LinkDecision|RetiredLinkDecision`, with
  `retired_reason`.** Written during implementation: the Migration relabels every converted verdict,
  so a query matching the live label alone exports one decision before the first boot after this
  change and none after it, silently — and the Reset screen calls the export the only copy.
  Retirement is not deletion, and ADR-014 turns on the verdict surviving somewhere a copy can reach.
  `retired_reason` travels with it because a verdict alone stops explaining itself once a decision
  can be retired for five different reasons (Migration).

## Migration

The migration has a vehicle, because a deliverable without one is a deletion nothing schedules —
the flaw this section exists to close. It is **`backend/src/policy_grapher/migrate.py`**, run at
application startup beside `db.py`'s constraint pass: idempotent, since everything it converts or
retires no longer matches its queries, with counts landing in the startup log and in its return
value, import-callable by the tests.

The same-document `:LinkDecision` recorded during the walkthrough is canonical and migrates to a
`:PairingDecision` — ADR-014 says no rebuild may discard a decision, and a schema change is not an
exception. The full mapping, since the migration must work from whatever it finds: `approve` →
`paired`, `reject` → `distinct`, carrying actor, rationale and timestamp — **and the pair is
re-oriented, not copied**. A `:LinkDecision` runs source→target with no chronology, and the one
live decision this migration exists for runs newer→older (`propagate.py:77-78`: the same-document
proposal promotes newer→older, which is how it met the `REMOVED` change). The reason is key
identity, not the diff: §3's lookup is orientation-normalized and would apply the verdict either
way, but §4's `key` is a **directional** hash, so a mis-oriented node carries a key no §6 POST
ever computes — a reviewer re-verdicting that pair would `MERGE` a second decision beside the
first instead of replacing it, and the 409 miscounts from then on. So the migration resolves each
obligation's edition through `:MANDATES`, orders the two by the corpus rule **including §6's
`version_id` tie-breaker**, and swaps where needed; both orientations occur in the wild and both
are handled. Conversion retires the original in the same transaction — relabelled
`:RetiredLinkDecision`, `retired_reason: 'converted'` — because a `:LinkDecision` that survives
its own conversion is still matched by `PROMOTE` and would resurrect its edge on the next
replay; the verdict's live form is the `:PairingDecision`. Two finds do not convert, each with
its own disposition:

- A *same-edition* `:LinkDecision` — reachable, because the rebuild API validates candidates by
  existence only and a version can be named as its own candidate, with only identical obligation
  ids skipped (`rebuilds.py:35-38`, `propose.py:131-135`) — answers neither vocabulary's question
  and cannot be oriented. It is **retired, not left**: relabelled `:RetiredLinkDecision` with
  every property intact plus a `retired_reason`, because a `:LinkDecision` left in place with
  `verdict: 'approve'` is matched by `PROMOTE` (`decisions.py:43-49`, no document predicate) on
  every review POST and every rebuild (`review.py:213`, `rebuild.py:163`), resurrecting a
  same-document `IMPLEMENTS` indefinitely — into Ask's undirected traversal
  (`retrieval/hybrid.py:62`), which no shipped guard reaches. Its promoted edge is deleted in the
  same transaction. The verdict survives under the archival label: ADR-014 honoured in letter and
  spirit.
- Two convertible `approve` decisions sharing an endpoint within one edition pair — recordable
  today, since `propose_links` writes a cross product and the review POST gates only on proposal
  existence (`propose.py:129-147`, `review.py:189-202`) — would convert into exactly the
  two-live-`paired`-verdicts state §6's 409 exists to refuse, minted by a writer the 409 does not
  guard. **Neither converts**: both are retired with `retired_reason: 'conflicting_pairing'` and
  counted, and the reviewer re-records the one they mean through §6, which enforces the conflict
  rule. A migration choosing the winner would be the design deciding what only a person may.

**Written during implementation, because two Criticals proved the paragraph above was not
enough.** Conflict cannot be detected by shared endpoints alone. Two decisions on ONE pair in
opposite orientations — `approve` one way, `reject` the other — map to the same canonical pair and
therefore the same key, and a screen that only inspects candidates already mapped to `paired`
never sees the rejection. Both then merge onto one node and the later write wins, with the source
query imposing no order, so *which human wins is undefined*. Separately, a conversion whose key is
already held by a live `:PairingDecision` — including one recorded through the normal route —
overwrites its verdict, actor, rationale and timestamp silently.

So the migration screens on the KEY, in both directions, exactly as `repoint_decisions` does: a
pre-batch check against keys already in the graph (retire, `retired_reason: 'pairing_exists'`,
never overwrite a verdict it did not make) and an in-batch check so two conversions cannot claim
one key (every member of the group retires as conflicting). Screening on keys rather than
endpoints is load-bearing in both directions: a legitimate `paired` on (X, Y) beside a `distinct`
on (X, Z) shares an endpoint and must still convert. Seeding the endpoint census from existing
`:PairingDecision`s also makes the conflict rule hold ACROSS runs — the migration runs at every
boot, so a rule enforced only within one run is not a rule.

Two further counts follow. A corrupt verdict retires as `unknown_verdict` rather than raising:
this runs at every boot, so raising makes one bad node unstartable for everyone, with no admin
route to reach and no export to take because the export sits behind the app that will not start.
And decisions whose obligations outlived their document — a state `DELETE /documents/{slug}`
produces, since it leaves obligations behind — are counted as `decisions_missing_documents` and
otherwise untouched: without documents they cannot be classified as same- or cross-document, and
retiring a legitimate implements verdict would be its own data loss. That count's zero is what
makes the others' completeness meaningful; non-zero means same-document `IMPLEMENTS` edges this
migration cannot reach, and the repair is document deletion cascading to obligations, which is a
separate story.

The justification for translating the verdict at all: a same-document `IMPLEMENTS`
question was only ever the pairing question in disguise — an edition does not discharge its
predecessor — so the migration recovers the judgement the reviewer actually made rather than
rewriting it.

Two edge classes do not wait for a rebuild, because nothing schedules one:

- **The promoted edge goes with its decision.** Migrating the `:LinkDecision` away leaves the
  same-document `IMPLEMENTS` it promoted with no decision tracing to it — `SUPPRESS` deletes only
  for `reject` (`decisions.py:53-60`) — and the shipped `propagate.py` guard does not reach Ask,
  whose hybrid traversal follows `IMPLEMENTS` undirected (`retrieval/hybrid.py:62`). The migration
  deletes that edge in the same transaction that converts its decision.
- **Same-document `IMPLEMENTS_PROPOSED` edges are deleted, not left to lapse.** `QUEUE` and
  `PENDING` match every proposal with no document predicate (`review.py:32-40`, `72-79`), and §8's
  `record_decision` guard makes same-document proposals undecidable — so leaving them "to
  disappear on the next rebuild" leaves the review queue serving proposals no verdict can clear,
  with `pending` inflated indefinitely. On the graph this design was written against that is not
  an edge case: all 119 walkthrough proposals ran between two editions of one instrument
  (`docs/backlog/backlog.md:181`). They are derived; the migration deletes them.

Live-graph counts quoted in earlier revisions (119 proposals, two decisions) are observations of a
dev graph on 2026-09-09, not repository facts, and the migration must be written to work from
whatever it finds.

**Take `GET /export` before the first boot after this ships.** The migration runs inside
`lifespan`, in one write transaction, with no dry run and no opt-out, so an operator cannot see its
counts until they are already facts. Everything it does is recoverable by hand — retirement keeps
the node and every property, and the `IMPLEMENTS`/`IMPLEMENTS_PROPOSED` edges it deletes are derived
— but the export is the only copy of a verdict, and it sits behind the app that runs the migration.
A step in the deploy note, not a setting: a dry-run flag would be a second code path over canonical
decisions, and the export already exists.

## Testing

- Same-document candidates produce no proposal; cross-document ones still do.
- The outcomes come from **two sites, not four lines**, and the fixtures must respect the
  containment. One chain fixture exercises the whole greedy loop: scores 0.90, 0.80 sharing the
  0.90 pair's partner, and a 0.76 tail — asserting `auto_paired`, `partner_taken`, and `contested`
  in one run; its mutation check is removing or reordering the `diff.py:155` check, which relabels
  the partner-taken pair `contested`. The `contested` label additionally gets a partner-free fork
  fixture — 0.80 and 0.78 sharing one clause, nothing accepted — so that label cannot be an
  artifact of a taken partner. `below_threshold` is asserted at the scoring filter, the only place
  it exists. A both-sides-taken fixture (0.95, 0.91, and an 0.85 sharing one endpoint with each)
  pins the two-winner join.
- **Recording must not change pairing.** A sub-threshold rival (say 0.74 beside a 0.78 pair) is
  recorded as a `PAIRING_CANDIDATE` and the 0.78 pair still auto-pairs — this kills the mutant
  that widens `scored` to `MIN_CONFIDENCE`, which would flip that pair to `contested` via
  `_best_elsewhere`.
- The sub-threshold bound holds and its timing is pinned: for a clause with several candidates in
  [0.30, 0.75), only the best and those within `PAIRING_MARGIN` of it are recorded; an
  `auto_paired` clause's sub-threshold candidate is kept only via an endpoint that finished the
  loop unpaired.
- A pair below `MIN_CONFIDENCE` is not recorded. **This is vacuous unless it mutates the floor**,
  since `score_pair` already returns `None` there (`propose.py:69-70`) — so it asserts against a
  deliberately lowered threshold, or it is not written.
- A `paired` decision yields `MODIFIED` across differing section paths — the case pass 2 cannot
  reach.
- **A `paired` decision beats the section rule**: the decision's old clause alone in a section
  with a *different* new clause still yields the decision's `MODIFIED`, and the section rule gets
  the remainder or declines. This is the fixture rev. 4 could not pass.
- A `distinct` decision suppresses a `MODIFIED` from pass 3 **and** one from pass 2.
- A `paired` decision naming an obligation pass 1 matched — its identical clause persists in the
  other edition — is counted in `pairings_unapplied` **in the GET response**, with the decision
  left intact.
- Re-diffing the same pair leaves no stale `PAIRING_CANDIDATE` behind, and leaves an **adjacent
  edition pair's candidates intact** — the `MANDATES`-scoped drop, which `drop_changes` cannot do.
- After a `distinct` verdict and a re-diff, the queue still returns the pair marked settled, and a
  `paired` POST on it succeeds — reversal needs no candidate edge.
- A POST on a never-recorded pair whose obligations belong to the two editions succeeds (the
  no-content-words case); a POST across two documents 404s; a POST given the pair newer-first is
  recorded older→newer regardless.
- A second `paired` verdict sharing an endpoint with a live one **in the same edition pair** is a
  409 naming the pairing to mark `distinct` first; a middle edition's clause paired into both
  adjacent pairs — B to its A-predecessor and to its C-successor — is accepted, and each diff
  applies only its own.
- **Two *concurrent* `paired` verdicts on one clause cannot both land**: two barriered sessions
  posting at once give one 200 and one 409, never two 200s, and the graph holds one live `paired`
  verdict afterwards. Asserted again with a `:PairingLock` for that edition pair already present,
  so the case where the `MERGE` matches rather than creates is covered too. Integration-marked,
  because the race needs two real sessions against a live database — and named here because
  removing the `lock_edition_pair` call together with `pairing_lock_key_unique` leaves the whole
  non-integration suite green, which makes this the one mechanism on the feature with no guard in
  the developer's own loop.
- **A decline is reachable when the page is full of pairings the diff made.** Asserted through the
  route: an unfiltered page capped below the number of `auto_paired` rows returns only those, the
  backlog breakdown still names the declined class and its count, and the same request with
  `outcome` set returns the decline. An unknown `outcome` is a 400, not an empty page.
- `GET /pairings/queue` returns candidates for an edition pair never opened in Triage, and 400s a
  reversed from/to instead of diffing it.
- A reversed *Triage* run followed by a chronological one leaves no orphaned candidate edge — the
  undirected drop, which a directional match would fail.
- The migrated walkthrough decision — recorded newer→older — is re-oriented, asserted through
  the observable that actually moves: a §6 POST on the same pair afterwards **replaces** the
  decision (one node, one key) instead of `MERGE`-ing a second beside it. §3's lookup cannot
  carry this test — it is orientation-normalized by design, so a mutant migration that skips the
  swap passes any diff-behaviour assertion.
- After the migration, `replay_decisions` recreates no same-document `IMPLEMENTS`: converted and
  same-edition finds alike are retired out of `PROMOTE`'s match, not deleted-around.
- Two approvals sharing an endpoint in one edition pair retire together; a migration that
  converts either is the mutant.
- A `distinct` verdict on a sub-threshold pair is neither re-recorded nor allowed to shadow the
  endpoint's next-best live candidate in the bound.
- The renamed `WHY_EMPTY` count does not report a false all-clear after §1, and the Review empty
  state's advice matches the new definition (its pinned wording test changes with it).
- A `:PairingDecision` recorded through the real write path appears in the export under its own
  category carrying both ids, verdict, actor, rationale and timestamp. Not "survives
  export → reset → import": no importer exists (`export.py` is export-only by design and the
  Reset screen says so), and the first export test asserted literals its own fixture wrote — the
  fixture must go through the recording function, as the repaired `:LinkDecision` test now does.
- A decision the Migration has **retired** is still exported, with its `retired_reason`, driven
  through the real migration rather than by CREATE-ing a relabelled node: the test that matters is
  the one that would have gone red when the first boot moved every legacy verdict out of the live
  label.
- A same-document `approve` already in the graph promotes nothing — `replay_decisions` returns
  `promoted: 0` and writes no edge — while a cross-document one still promotes. The mutant is
  `PROMOTE` without its document predicate.
- A `:LinkDecision` one of whose obligation nodes is gone is counted by the Migration rather than
  reported as a clean graph, and is left exactly as it was for the repoint path to repair.
- End-to-end: a cross-document `IMPLEMENTS` over a confirmed pairing yields a Triage row with the
  correct `previous_statement`.

Each mutation-checked, per the sprint Definition of Done (`docs/sprints/sprint-12/plan.md:96` —
not an AGENTS.md standing rule, which rev. 3 misattributed). Two of this session's tests passed
first time and were wrong — one asserted against a single-proposal fixture where the backlog and
page size coincide, one had the link direction reversed.

## Consequences

**Makes easy.** The pairs the diff refuses stop being invisible, and the ones it guessed become
correctable. Two questions, two screens, two vocabularies.

**Makes hard.** Two canonical decision types, and the repoint path becomes generic to serve both —
a real refactor of the most safety-critical code in the phase. `PAIRING_CANDIDATE`'s lifecycle must
stay welded to the diff's, and a writer that forgets its drop reintroduces exactly the orphaning
ADR-039 was written about.

**Commits us to.** A person overriding the measure in both directions. The bar may auto-pair above
0.75 and the section rule may pair on structure, but neither outranks a human — `paired` is
applied before the section rule and the POST needs no recorded edge, so the commitment is
mechanical, not aspirational. The one exception is named: pass 1 can pre-empt a verdict, because
an identical clause persisting in both editions is a fact rather than a judgement, and it is
counted, never silent — ADR-032's position for merging documents, for the same reason.
