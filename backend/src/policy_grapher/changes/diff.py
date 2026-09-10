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

**`MODIFIED` is found by section, not by text similarity.** Nothing here measures
how alike two sentences are. A section that holds exactly one unmatched clause on
each side has been edited, and that is a fact about the document's structure. A
section holding several falls back to `ADDED`/`REMOVED` and says so in the
summary, because pairing two against two is a guess, and a wrong guess points a
reviewer at the wrong sentence with no indication that it did.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import normalize
from policy_grapher.links.propose import MIN_CONFIDENCE, score_pairing

ADDED = "ADDED"
REMOVED = "REMOVED"
MODIFIED = "MODIFIED"
KINDS = (ADDED, REMOVED, MODIFIED)

AMBIGUOUS_SECTION = (
    "Section {section} holds more than one obligation that changed, so this is "
    "reported as a removal and an addition rather than a guessed pairing."
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
                    (candidate.confidence, candidate.rationale, before, after)
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
                        "outcome": "below_threshold",
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
                for confidence, _r, before, after in scored
                if obligation_id in (before["id"], after["id"])
                and partner_id not in (before["id"], after["id"])
            ),
            default=0.0,
        )

    for confidence, rationale, before, after in scored:
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
                    "outcome": "partner_taken",
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
                    "outcome": "contested",
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
                "outcome": "auto_paired",
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
                "summary": (
                    f"The obligation moved from section "
                    f"{'/'.join(before['section_path'])} to "
                    f"{'/'.join(after['section_path'])} and was reworded — "
                    f"{rationale}"
                ),
            }
        )

    # The scoring loop is a cross product, so recording everything under the bar
    # would write thousands of edges per edition pair and bury the one candidate
    # worth a look under its own long tail. A sub-threshold record is kept iff at
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

    `decisions` maps (old_obligation_id, new_obligation_id) to a reviewer's
    verdict, threaded down by `diff_versions` rather than fetched here. The
    parameter is part of the planning signature from the start; the rules that
    read it land with the pairing-decision passes, and until then it is
    accepted and unread — passing None is always safe.
    """
    unmatched_old = {k: v for k, v in old.items() if k not in new}
    unmatched_new = {k: v for k, v in new.items() if k not in old}

    by_section_old = defaultdict(list)
    by_section_new = defaultdict(list)
    for entry in unmatched_old.values():
        by_section_old[tuple(entry["section_path"])].append(entry)
    for entry in unmatched_new.values():
        by_section_new[tuple(entry["section_path"])].append(entry)

    changes: list[dict] = []
    candidates: list[dict] = []
    paired_old: set[str] = set()
    paired_new: set[str] = set()

    for section, news in by_section_new.items():
        olds = by_section_old.get(section, [])
        if len(olds) == 1 and len(news) == 1:
            before, after = olds[0], news[0]
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
        unmatched_old,
        unmatched_new,
        paired_old,
        paired_new,
        changes,
        candidates,
        distinct=set(),
    )

    def _ambiguous(section: tuple[str, ...]) -> str | None:
        if len(by_section_old.get(section, [])) + len(by_section_new.get(section, [])) > 1:
            return AMBIGUOUS_SECTION.format(section="/".join(section))
        return None

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
                "summary": _ambiguous(section)
                or f"The obligation in section {'/'.join(section)} is gone.",
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
                "summary": _ambiguous(section)
                or f"A new obligation appears in section {'/'.join(section)}.",
            }
        )

    return PlanResult(changes=changes, candidates=candidates, pairings_unapplied=0)


def drop_changes(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove every change touching an edition, from either side.

    Called by a rebuild: obligations are dropped and recreated there, and a
    `:Change` whose `AFFECTS` target went with them would linger pointing at
    nothing — a change a reviewer can see but not trace.
    """
    summary = tx.run(DROP_FOR_VERSION, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted


def diff_versions(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[str, int]:
    """Diff two editions and write the result. Returns counts by kind.

    Drops this pair's existing changes first rather than merging over them: a
    re-extraction can make a change stop existing, and a `:Change` left behind
    shows a reviewer a change that is no longer real. Ids are deterministic, so
    the changes that *do* still exist come back identical.
    """
    old = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": from_version_id}))
    new = _by_key(tx.run(READ_OBLIGATIONS, {"version_id": to_version_id}))

    tx.run(
        DROP_PAIR,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).consume()

    plan = _plan_changes(old, new)
    changes = plan.changes
    for change in changes:
        change["change_id"] = change_id(
            from_version_id, to_version_id, change["kind"], change["obligation_id"]
        )

    if changes:
        tx.run(
            WRITE_CHANGES,
            {
                "from_version_id": from_version_id,
                "to_version_id": to_version_id,
                "changes": changes,
            },
        ).consume()

    counts = dict.fromkeys(KINDS, 0)
    for change in changes:
        counts[change["kind"]] += 1
    return counts
