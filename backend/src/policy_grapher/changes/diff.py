"""Diff two editions of one instrument into `:Change` nodes.

**What the diff matches on, and why it is not `obligation_id`.** An
`obligation_id` hashes the version it belongs to (ADR-013), which is what lets a
Phase 4 decision record which *edition* a reviewer approved. The consequence is
that a clause reproduced word for word in two editions carries two different ids,
so matching on id would report every obligation in the document as a removal plus
an addition — the failure mode this module exists to avoid, applied to the whole
document rather than just the reworded clauses. The diff therefore matches on the
version-independent part of the identity: the section the clause sits in and its
normalized statement.

**Four things can pair two clauses, and they form a precedence chain.** A
reviewer's recorded `paired` verdict is applied first and *consumes* both clauses,
so nothing below can re-decide them. Pass 1 then matches a clause reproduced word
for word — the one thing that may pre-empt a verdict, because an identical clause
persisting in both editions is a fact rather than a judgement, and it is counted
when it does. Pass 2 is the section rule: a section holding exactly one unmatched
clause on each side has been edited, and that is a fact about the document's
structure, which no measurement improves on. Pass 3 is the wording pass, which
*does* measure how alike two statements are — `links.propose.score_pairing`,
shared content words weighted by shared designators (ADR-031) — above a higher bar
than the proposer's, and which declines rather than guesses when two candidates
score within a hair of each other. A section holding several unmatched clauses
that the wording pass could not pair falls back to `ADDED`/`REMOVED` and says so
in the summary, because pairing two against two is a guess, and a wrong guess
points a reviewer at the wrong sentence with no indication that it did.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import normalize
from policy_grapher.links.pairing import PairingVerdict, read_pairings
from policy_grapher.links.propose import MIN_CONFIDENCE, score_pairing

ADDED = "ADDED"
REMOVED = "REMOVED"
MODIFIED = "MODIFIED"
KINDS = (ADDED, REMOVED, MODIFIED)

# What the wording pass decided about one pair, in the order its rules fire.
# Named constants rather than literals at the four append sites because the
# pairing queue filters on these strings: a route validating against its own
# hand-written list would stop matching the day a label changed here, and an
# unmatched filter value reads as an empty queue — "nothing to settle" — which
# is the one answer this feature must never give by accident.
AUTO_PAIRED = "auto_paired"
PARTNER_TAKEN = "partner_taken"
CONTESTED = "contested"
BELOW_THRESHOLD = "below_threshold"
OUTCOMES = (AUTO_PAIRED, PARTNER_TAKEN, CONTESTED, BELOW_THRESHOLD)

AMBIGUOUS_SECTION = (
    "Section {section} holds more than one obligation that changed, so this is "
    "reported as a removal and an addition rather than a guessed pairing."
)

# The decline a *person* made, which must never be reported as the one above.
# A section holding one changed obligation on each side is not ambiguous, and
# saying it is blames the pairing rule for a reviewer's decision — the reviewer
# reads their own verdict back as the machine's excuse for not guessing. The
# wording is this module's own: the spec requires pass 2 to honour `distinct`
# but does not fix the sentence.
SETTLED_DISTINCT = (
    "A reviewer recorded the two clauses that changed in section {section} as "
    "distinct, so this is reported as a removal and an addition rather than a "
    "pairing."
)

READ_OBLIGATIONS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN o.obligation_id AS id,
       o.statement     AS statement,
       o.modality      AS modality,
       o.section_path  AS section_path
"""

DROP_PAIR = """
MATCH (c:Change)-[:FROM_VERSION]->(:DocumentVersion {version_id: $from_version_id})
MATCH (c)-[:TO_VERSION]->(:DocumentVersion {version_id: $to_version_id})
DETACH DELETE c
"""

DROP_FOR_VERSION = """
MATCH (c:Change)-[:FROM_VERSION|TO_VERSION]->(:DocumentVersion {version_id: $version_id})
DETACH DELETE c
"""

WRITE_CHANGES = """
MATCH (from_version:DocumentVersion {version_id: $from_version_id})
MATCH (to_version:DocumentVersion {version_id: $to_version_id})
UNWIND $changes AS change
MATCH (affected:Obligation {obligation_id: change.obligation_id})
MERGE (c:Change {change_id: change.change_id})
SET c.kind               = change.kind,
    c.section_path       = change.section_path,
    c.statement          = change.statement,
    c.previous_statement = change.previous_statement,
    c.modality           = change.modality,
    c.summary            = change.summary
MERGE (c)-[:FROM_VERSION]->(from_version)
MERGE (c)-[:TO_VERSION]->(to_version)
MERGE (c)-[:AFFECTS]->(affected)
"""

# The candidate edge is written from-side→to-side, whatever the caller passed:
# neither this statement nor `diff_versions` knows chronology — they carry
# request order, and older→newer is pinned at the pairing route, the one place
# built on these edges. No version anchors here: obligation ids are unique, and
# the pairs being written were read from the two named editions in this same
# transaction.
WRITE_CANDIDATES = """
UNWIND $candidates AS candidate
MATCH (old:Obligation {obligation_id: candidate.old_id})
MATCH (new:Obligation {obligation_id: candidate.new_id})
MERGE (old)-[r:PAIRING_CANDIDATE]->(new)
SET r.confidence = candidate.confidence,
    r.rationale  = candidate.rationale,
    r.outcome    = candidate.outcome
"""

# Undirected on the candidate edge, deliberately: a Triage GET run with the pair
# reversed writes its edges the other way, and a directional drop would delete
# only the well-oriented ones while leaving those orphaned forever. Anchored
# through :MANDATES on *both* ends, because a middle edition's obligations
# belong to two pairs — "any edge touching either edition" would delete the
# neighbouring diff's candidates. DROP_PAIR's scoping cannot transfer: it scopes
# through the :Change node's FROM_VERSION/TO_VERSION, which a bare relationship
# does not carry.
DROP_CANDIDATES = """
MATCH (:DocumentVersion {version_id: $from_version_id})-[:MANDATES]->(:Obligation)
      -[r:PAIRING_CANDIDATE]-
      (:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $to_version_id})
DELETE r
"""


def content_key(section_path: list[str], statement: str) -> str:
    """How one clause is recognised across editions.

    Deliberately not `obligation_id`: that one includes the version, so it can
    never match across the two editions being compared. Normalization is the same
    (`extraction.schema.normalize`), so a reflowed or re-cased line is the same
    clause here exactly as it is there.
    """
    return f"{'/'.join(section_path)}|{normalize(statement)}"


def change_id(
    from_version_id: str, to_version_id: str, kind: str, obligation_id: str
) -> str:
    key = f"{from_version_id}|{to_version_id}|{kind}|{obligation_id}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def _by_key(records) -> dict[str, dict]:
    return {content_key(r["section_path"], r["statement"]): dict(r) for r in records}


# Higher than the proposer's threshold, deliberately (ADR-031). The proposer offers
# a candidate to a human who accepts or rejects it; this writes a MODIFIED nobody
# reviews. The cost of a wrong answer is not symmetric, so the bar is not the same.
PAIRING_CONFIDENCE = 0.75

# Two candidates this close are not distinguishable by this measure, and picking
# the higher would be picking whichever the dictionary happened to yield first.
# ADR-015's answer to "we do not know" is to say so, and ADR-031 keeps it.
PAIRING_MARGIN = 0.05


@dataclass(frozen=True)
class PlanResult:
    """What one planning run decided, in full: the changes to write, every
    wording-pass candidate labelled with the first rule that fired for it, and
    how many reviewer verdicts the plan could not apply."""

    changes: list[dict]
    candidates: list[dict]
    pairings_unapplied: int


def _pair_by_wording(
    unmatched_old: dict[str, dict],
    unmatched_new: dict[str, dict],
    paired_old: set[str],
    paired_new: set[str],
    changes: list[dict],
    candidates: list[dict],
    distinct: set[frozenset[str]],
) -> None:
    """Pair what section-based matching left over — ADR-031.

    Greedy over the best-scoring pairs rather than optimal: an assignment problem
    would be a better answer to a question nobody is asking, since a document that
    reworded dozens of clauses into each other's sections is one no pairing rule
    should be confident about anyway.

    Every outcome lands in `candidates`, labelled with the first rule that fired
    for it rather than with a predicate of its own. `below_threshold` is settled
    first, in the scoring loop, before any pairing is attempted; the other three
    are decided in the greedy loop, which tests `partner_taken`, then
    `contested`, and labels whatever survives both `auto_paired`. That order is
    load-bearing rather than incidental: `partner_taken`'s predicate is a strict
    subset of `contested`'s — the consuming pair scores at least as high and
    shares an endpoint, so the margin rule would decline the same pair — so a
    pair answering to both is reported as `partner_taken`, the label that has an
    `auto_paired` winner to point a reviewer at.

    `distinct` holds pairs a reviewer has ruled out. They are skipped before
    scoring, which keeps them out of `scored`, out of the sub-threshold
    accumulator, and out of the bound's notion of an endpoint's best: a score
    the reviewer rejected must not shadow the endpoint's next-best live
    candidate.
    """
    scored: list[tuple[float, str, dict, dict]] = []
    sub_threshold: list[dict] = []
    for before in unmatched_old.values():
        if before["id"] in paired_old:
            continue
        for after in unmatched_new.values():
            if after["id"] in paired_new:
                continue
            if frozenset((before["id"], after["id"])) in distinct:
                continue
            candidate = score_pairing(after["statement"], before["statement"])
            if candidate is None:
                continue
            if candidate.confidence >= PAIRING_CONFIDENCE:
                scored.append(
                    (
                        candidate.confidence,
                        candidate.rationale,
                        candidate.facts,
                        before,
                        after,
                    )
                )
            elif candidate.confidence >= MIN_CONFIDENCE:
                # The floor is this module's own, not inherited: the scorer
                # returns None below MIN_CONFIDENCE today, but recording is
                # bounded here so a retuned scorer cannot silently widen it.
                sub_threshold.append(
                    {
                        "old_id": before["id"],
                        "new_id": after["id"],
                        "confidence": candidate.confidence,
                        "rationale": candidate.rationale,
                        "outcome": BELOW_THRESHOLD,
                    }
                )

    scored.sort(key=lambda row: row[0], reverse=True)

    # The best score each obligation could have achieved with a *different*
    # partner. A pair that only just beats its own runner-up is not a pairing this
    # measure can distinguish, and choosing anyway would be choosing whichever the
    # dictionary happened to yield first. Scans only `scored`, so everything here
    # is >= PAIRING_CONFIDENCE — widening that would change which pairs are made,
    # not merely which are recorded.
    def _best_elsewhere(obligation_id: str, partner_id: str) -> float:
        return max(
            (
                confidence
                for confidence, _rationale, _facts, before, after in scored
                if obligation_id in (before["id"], after["id"])
                and partner_id not in (before["id"], after["id"])
            ),
            default=0.0,
        )

    for confidence, rationale, facts, before, after in scored:
        if before["id"] in paired_old or after["id"] in paired_new:
            # An endpoint went to a higher-scoring pair earlier in this loop.
            # Checked before the margin, and the order is load-bearing: the
            # consuming pair also satisfies the margin predicate, and this is
            # the actionable label — an auto_paired winner exists to point at.
            candidates.append(
                {
                    "old_id": before["id"],
                    "new_id": after["id"],
                    "confidence": confidence,
                    "rationale": rationale,
                    "outcome": PARTNER_TAKEN,
                }
            )
            continue
        contested = max(
            _best_elsewhere(before["id"], after["id"]),
            _best_elsewhere(after["id"], before["id"]),
        )
        if confidence - contested < PAIRING_MARGIN:
            # Two candidates within a hair of each other: both stay ADDED/REMOVED
            # and the summary says why, which is ADR-015's answer kept.
            candidates.append(
                {
                    "old_id": before["id"],
                    "new_id": after["id"],
                    "confidence": confidence,
                    "rationale": rationale,
                    "outcome": CONTESTED,
                }
            )
            continue

        paired_old.add(before["id"])
        paired_new.add(after["id"])
        candidates.append(
            {
                "old_id": before["id"],
                "new_id": after["id"],
                "confidence": confidence,
                "rationale": rationale,
                "outcome": AUTO_PAIRED,
            }
        )
        changes.append(
            {
                "kind": MODIFIED,
                "obligation_id": after["id"],
                "section_path": after["section_path"],
                "statement": after["statement"],
                "previous_statement": before["statement"],
                "modality": after["modality"],
                # `facts`, not `rationale`. The rationale ends with the pairing
                # reviewer's question, and this line is read on Triage by
                # someone asking a different one — by the time a change reaches
                # them the pairing has been decided, and the row exists because
                # it was. The question stays on the candidate, where the pairing
                # reviewer reads it.
                "summary": (
                    f"The obligation moved from section "
                    f"{'/'.join(before['section_path'])} to "
                    f"{'/'.join(after['section_path'])} and was reworded — "
                    f"{facts}"
                ),
            }
        )

    # The scoring loop is a cross product, so recording everything under the bar
    # would write thousands of edges per edition pair and bury the one candidate
    # worth a look under its own long tail.
    #
    # Everything at or *above* the bar is recorded unconditionally and is
    # deliberately not bounded the same way: those records are the pass's own
    # decisions, and every bound anyone has proposed drops declines — which are
    # the rows the pairing queue exists to show. The cost is real and is write
    # volume per GET, not correctness: a wholly renumbered 30-clause edition
    # measured 900 candidate edges, and the count is quadratic in unmatched
    # clauses. Reachability is handled where it is a reading problem rather than a
    # writing one — the queue filters by outcome (routers/pairings.py) — and a
    # bound here would have to say which of a reviewer's questions it is throwing
    # away.
    #
    # A sub-threshold record is kept iff at
    # least one of its endpoints finished the greedy loop unpaired AND it is that
    # endpoint's best sub-threshold candidate or within PAIRING_MARGIN of that
    # best. Judged after the loop, deliberately: before it, every endpoint is
    # still unpaired and this filter would keep the lot.
    best_sub: dict[str, float] = {}
    for record in sub_threshold:
        for endpoint in (record["old_id"], record["new_id"]):
            best_sub[endpoint] = max(
                best_sub.get(endpoint, 0.0), record["confidence"]
            )

    for record in sub_threshold:
        if (
            record["old_id"] not in paired_old
            and best_sub[record["old_id"]] - record["confidence"] < PAIRING_MARGIN
        ) or (
            record["new_id"] not in paired_new
            and best_sub[record["new_id"]] - record["confidence"] < PAIRING_MARGIN
        ):
            candidates.append(record)


def _plan_changes(
    old: dict[str, dict],
    new: dict[str, dict],
    decisions: dict[tuple[str, str], str] | None = None,
) -> PlanResult:
    """Work out the changes without touching the graph, so the rule is testable
    on its own and readable in one place.

    `decisions` is `{(old_obligation_id, new_obligation_id): verdict}` exactly
    as `links.pairing.read_pairings` returns it — a plain dict for the same
    reason `old` and `new` are plain dicts: no `tx` in here.
    """
    unmatched_old = {k: v for k, v in old.items() if k not in new}
    unmatched_new = {k: v for k, v in new.items() if k not in old}

    changes: list[dict] = []
    candidates: list[dict] = []
    distinct: set[frozenset[str]] = set()
    pairings_unapplied = 0

    # A reviewer's verdicts, applied while the only structure that exists is
    # the two unmatched sets. Pass 2 pairs unconditionally and reads only the
    # by_section grouping built below, so a `paired` verdict applied any later
    # can be outranked by a structural heuristic — the inversion the design
    # forbids. Consuming means *deleting* from the unmatched dicts, not
    # marking: pass 2 never reads the paired sets, and a settled clause must
    # not count toward a section's ambiguity tally either. Only pass 1 may
    # pre-empt a verdict — an identical clause persisting in both editions is
    # a fact, not a pairing judgement — and that pre-emption is counted, never
    # silent. The keys arrive in the record's canonical older→newer
    # orientation, but this layer binds whatever from/to the caller passed (a
    # reversed Triage run flips the sides), so both orientations are tried.
    #
    # `pairings_unapplied` therefore means "pass 1 got there first", and that
    # is the only reason it may ever be non-zero. Two live `paired` verdicts
    # sharing an endpoint would break that: the first pops the shared clause
    # and the second's lookup then fails, counting a conflict between two
    # reviewers as a pass-1 pre-emption. **This code depends on that state not
    # reaching the graph, and every writer of a `:PairingDecision` refuses it.**
    # The pairing route answers the second verdict with a 409 scoped to the
    # edition pair — so a middle edition's clause may still pair into both of
    # its adjacent pairs — and takes that pair's lock before reading, because
    # under read-committed the conflict read alone serialises nothing
    # (`routers/pairings.py`, `links.pairing.lock_edition_pair`). The startup
    # migration screens the same state on keys and on paired endpoints, seeded
    # from the decisions already in the graph so the rule holds across boots
    # (`migrate.py`). And `repoint_decisions` cannot collapse two verdicts onto
    # one pair: two obligations sharing a statement are ambiguous and go
    # unrepointed (`links/decisions.py`).
    #
    # `paired` and `distinct` can both name the same two obligations, because
    # `pairing_key` is directional and the two orientations are two records.
    # `paired` wins, and wins whichever order the dict yields: the paired arm
    # never consults `distinct`, and once it pops the two clauses neither pass
    # 2 nor pass 3 can see them to decline. Stated because it is a resolution,
    # not an accident — a reader should not have to derive it from iteration
    # order — and pinned by a test.
    by_id_old = {entry["id"]: key for key, entry in unmatched_old.items()}
    by_id_new = {entry["id"]: key for key, entry in unmatched_new.items()}
    for (first, second), verdict in (decisions or {}).items():
        if verdict == PairingVerdict.DISTINCT:
            # Orientation-free by construction — a frozenset of the two ids —
            # so the reversed-run problem the paired arm handles above cannot
            # arise here. `_pair_by_wording` drops these from `scored`, from
            # the sub-threshold recording, and from the bound's "best": the
            # reviewer said *not this one*, so its score must not shadow the
            # endpoint's next-best live candidate.
            distinct.add(frozenset((first, second)))
            continue
        if verdict != PairingVerdict.PAIRED:
            # Matched explicitly rather than reached by falling through the
            # arm above, which would apply *any* unrecognised string as a
            # pairing and caption it as a human decision — silently honouring
            # a verdict nobody wrote, in the more consequential direction.
            # Ignored here, as `replay_decisions` ignores a `:LinkDecision`
            # verdict it does not recognise: neither arm claims it, so the
            # pair simply stays unsettled. Deliberately *not* counted —
            # `pairings_unapplied` means pass 1 pre-empted a verdict, and a
            # corrupt row is not that. `record_pairing` validates every write,
            # so reaching this branch means the graph was written around it.
            continue
        forward = (by_id_old.get(first), by_id_new.get(second))
        backward = (by_id_old.get(second), by_id_new.get(first))
        if forward[0] in unmatched_old and forward[1] in unmatched_new:
            old_key, new_key = forward
        elif backward[0] in unmatched_old and backward[1] in unmatched_new:
            old_key, new_key = backward
        else:
            pairings_unapplied += 1
            continue
        before = unmatched_old.pop(old_key)
        after = unmatched_new.pop(new_key)
        changes.append(
            {
                "kind": MODIFIED,
                "obligation_id": after["id"],
                "section_path": after["section_path"],
                "statement": after["statement"],
                "previous_statement": before["statement"],
                "modality": after["modality"],
                # No "newer"/"older" here: this module binds whatever from/to
                # the caller passed and says so, `/triage` takes both version
                # ids from the request, and the `backward` branch above exists
                # precisely because a reversed run flips the sides. Naming a
                # chronology this layer cannot derive would put the claim in
                # front of a reviewer the wrong way round on exactly those
                # runs. What it can say is that the two are one obligation.
                "summary": (
                    "A reviewer paired these clauses: they are one obligation, "
                    "reworded between these two editions."
                ),
            }
        )

    by_section_old = defaultdict(list)
    by_section_new = defaultdict(list)
    for entry in unmatched_old.values():
        by_section_old[tuple(entry["section_path"])].append(entry)
    for entry in unmatched_new.values():
        by_section_new[tuple(entry["section_path"])].append(entry)

    paired_old: set[str] = set()
    paired_new: set[str] = set()
    # Clauses this pass declined because a reviewer ruled them distinct. They
    # still become ADDED/REMOVED — that is what "not the same clause" means —
    # but they are not the ambiguity `_ambiguous` describes, and they carry
    # their own sentence. Before verdicts existed this pass never declined a
    # one-each-side section, so the false ambiguity is newly reachable.
    settled_distinct: set[str] = set()

    for section, news in by_section_new.items():
        olds = by_section_old.get(section, [])
        if len(olds) == 1 and len(news) == 1:
            before, after = olds[0], news[0]
            if frozenset((before["id"], after["id"])) in distinct:
                # The reviewer said these are not the same clause. This rule
                # pairs on structure alone and would re-pair them; a human
                # verdict outranks it, so the pair falls through to
                # ADDED/REMOVED like any other decline.
                settled_distinct.add(before["id"])
                settled_distinct.add(after["id"])
                continue
            paired_old.add(before["id"])
            paired_new.add(after["id"])
            changes.append(
                {
                    "kind": MODIFIED,
                    # The new obligation: it is the one a reviewer must now act on.
                    "obligation_id": after["id"],
                    "section_path": after["section_path"],
                    "statement": after["statement"],
                    "previous_statement": before["statement"],
                    "modality": after["modality"],
                    "summary": (
                        f"The obligation in section {'/'.join(section)} was reworded."
                    ),
                }
            )

    # ADR-031. What section-based pairing could not reach gets a second pass on
    # wording. Structure first, always: a section holding one unmatched clause
    # each side has been edited, and no measurement improves on a certainty.
    #
    # The measure is `links/propose.py`'s, unchanged — shared content words
    # weighted by shared designators, scored against the shorter statement. It
    # keeps every row explainable by a path a person can walk, which is what
    # ADR-015 actually required; "no text similarity" was the mechanism, not the
    # constraint.
    _pair_by_wording(
        unmatched_old, unmatched_new, paired_old, paired_new, changes, candidates, distinct
    )

    def _ambiguous(section: tuple[str, ...]) -> str | None:
        if len(by_section_old.get(section, [])) + len(by_section_new.get(section, [])) > 1:
            return AMBIGUOUS_SECTION.format(section="/".join(section))
        return None

    def _decline_summary(entry: dict, section: tuple[str, ...], plain: str) -> str:
        """Why this clause is its own change rather than half of a pairing.

        The settled check comes first and `_ambiguous` is never consulted for
        those two clauses, which is the whole fix: their section holds exactly
        one changed obligation on each side, so the tally reads 2 and would
        report ambiguity for a pair a person had already decided. No filtering
        inside `_ambiguous` is needed to achieve that — pass 2 only reaches its
        `distinct` decline when the section holds those two clauses and nothing
        else, so there is no third clause in there whose tally they could
        distort.
        """
        # The caveat *after* the description, never instead of it. Returning
        # only the caveat meant the one line an analyst gets explained the
        # diff's own bookkeeping — why this reads as a removal and an addition —
        # and never said the obligation had gone. Both facts fit in a sentence
        # each, and the reader's comes first.
        if entry["id"] in settled_distinct:
            return f"{plain} {SETTLED_DISTINCT.format(section='/'.join(section))}"
        ambiguous = _ambiguous(section)
        return f"{plain} {ambiguous}" if ambiguous else plain

    for entry in unmatched_old.values():
        if entry["id"] in paired_old:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": REMOVED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _decline_summary(
                    entry,
                    section,
                    f"The obligation in section {'/'.join(section)} is gone.",
                ),
            }
        )

    for entry in unmatched_new.values():
        if entry["id"] in paired_new:
            continue
        section = tuple(entry["section_path"])
        changes.append(
            {
                "kind": ADDED,
                "obligation_id": entry["id"],
                "section_path": entry["section_path"],
                "statement": entry["statement"],
                "previous_statement": None,
                "modality": entry["modality"],
                "summary": _decline_summary(
                    entry,
                    section,
                    f"A new obligation appears in section {'/'.join(section)}.",
                ),
            }
        )

    return PlanResult(
        changes=changes, candidates=candidates, pairings_unapplied=pairings_unapplied
    )


def drop_changes(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove every change touching an edition, from either side.

    Called by a rebuild: obligations are dropped and recreated there, and a
    `:Change` whose `AFFECTS` target went with them would linger pointing at
    nothing — a change a reviewer can see but not trace.
    """
    summary = tx.run(DROP_FOR_VERSION, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted


def drop_candidates(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> int:
    """Remove one edition pair's candidate edges, from either orientation.

    `drop_changes` cannot reach these: it DETACH-deletes `:Change` nodes, and a
    relationship between two `:Obligation` nodes hangs off no `:Change`. On the
    rebuild path the edges happen to die with `drop_obligations`' DETACH DELETE
    — by accident, from a different statement — and not at all on the re-diff
    path, which is the one this exists for. The count is
    `relationships_deleted`: nothing here deletes a node.

    That accidental death is wider than this function's scope, and the
    difference matters to anyone reasoning about the two together: DETACH
    DELETE takes every edge touching the rebuilt edition's obligations, so
    rebuilding one edition clears the candidate record of *every* pair that
    edition belongs to — a middle edition's rebuild wipes the neighbouring
    pair's candidates as well as its own. This function is deliberately
    narrower, anchored through :MANDATES on both ends; the neighbouring pair
    gets its record back only when that pair is diffed again.
    """
    summary = tx.run(
        DROP_CANDIDATES,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()
    return summary.counters.relationships_deleted


def diff_versions(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[str, int]:
    """Diff two editions and write the result. Returns counts by kind, plus
    `pairings_unapplied` — `paired` verdicts pass 1 pre-empted on this run.

    Drops this pair's existing changes and candidates first rather than
    merging over them: a re-extraction can make either stop existing, and a
    stale record shows a reviewer something that is no longer real. Ids are
    deterministic, so what *does* still exist comes back identical.

    The reviewer's pairing decisions are read here and threaded down — scoped
    through :MANDATES to the two named editions, so a middle edition's verdict
    cannot leak into a neighbouring pair's diff, and a verdict recorded on the
    pairing screen applies on the very next diff with no wiring by any caller.
    """
    old = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": from_version_id}))
    new = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": to_version_id}))

    tx.run(
        DROP_PAIR,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()
    drop_candidates(
        tx, from_version_id=from_version_id, to_version_id=to_version_id
    )

    decisions = read_pairings(
        tx, from_version_id=from_version_id, to_version_id=to_version_id
    )
    result = _plan_changes(old, new, decisions)
    for change in result.changes:
        change["change_id"] = change_id(
            from_version_id, to_version_id, change["kind"], change["obligation_id"]
        )

    if result.changes:
        tx.run(
            WRITE_CHANGES,
            {
                "from_version_id": from_version_id,
                "to_version_id": to_version_id,
                "changes": result.changes,
            },
        ).consume()
    if result.candidates:
        tx.run(WRITE_CANDIDATES, {"candidates": result.candidates}).consume()

    counts = dict.fromkeys(KINDS, 0)
    for change in result.changes:
        counts[change["kind"]] += 1
    counts["pairings_unapplied"] = result.pairings_unapplied
    return counts
