"""Human verdicts on proposed links, and the one path that promotes them.

`:LinkDecision` is **canonical**. Everything else this phase writes is derived and
droppable; a decision is a thing a person did, and no rebuild may discard it. That
is the whole reason it is a node of its own rather than a property on the edge —
the edge is derived, so a property on it would be dropped with it.

`replay_decisions` is the **only** writer of `IMPLEMENTS` anywhere in the codebase.
Nothing promotes a link directly, so there is exactly one code path to audit: a
proposal exists, a human verdicts it, replay applies the verdict.
"""

import hashlib
from enum import StrEnum

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import normalize


class Verdict(StrEnum):
    """Closed on purpose: `replay_decisions` branches on this value, so a verdict
    it does not recognise would be silently skipped — an approval that never
    promotes and reports no error."""

    APPROVE = "approve"
    REJECT = "reject"


RECORD_DECISION = """
MERGE (d:LinkDecision {key: $key})
SET d.source_obligation_id = $source_id,
    d.target_obligation_id = $target_id,
    d.verdict              = $verdict,
    d.actor                = $actor,
    d.rationale            = $rationale,
    d.at                   = datetime()
"""

# Approvals whose obligations both still exist. Written as a MERGE so replay is
# idempotent, and scoped by the decision so nothing else can reach this edge type.
PROMOTE = """
MATCH (d:LinkDecision {verdict: 'approve'})
MATCH (source:Obligation {obligation_id: d.source_obligation_id})
MATCH (target:Obligation {obligation_id: d.target_obligation_id})
MERGE (source)-[:IMPLEMENTS]->(target)
RETURN count(*) AS promoted
"""

# Rejections: ensure no such edge exists. Deleting rather than merely not creating
# matters because a pair may have been approved before and rejected since.
SUPPRESS = """
MATCH (d:LinkDecision {verdict: 'reject'})
OPTIONAL MATCH (source:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (target:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(d) AS suppressed
"""

# Approvals that cannot be applied because re-extraction no longer produces one
# side. The decision stays — it is a fact a human established — but the graph
# cannot express it, and a caller has to be told rather than left to assume the
# replay was complete.
UNPROMOTABLE = """
MATCH (d:LinkDecision {verdict: 'approve'})
WHERE NOT EXISTS { MATCH (:Obligation {obligation_id: d.source_obligation_id}) }
   OR NOT EXISTS { MATCH (:Obligation {obligation_id: d.target_obligation_id}) }
RETURN count(d) AS unpromotable
"""


READ_OBLIGATION_STATEMENTS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN o.obligation_id AS obligation_id, o.statement AS statement
"""

READ_DECISIONS_FOR = """
UNWIND $ids AS id
MATCH (d:LinkDecision)
WHERE d.source_obligation_id = id OR d.target_obligation_id = id
RETURN DISTINCT d.key AS key,
       d.source_obligation_id AS source_id,
       d.target_obligation_id AS target_id
"""

APPLY_REPOINT = """
UNWIND $moves AS m
MATCH (d:LinkDecision {key: m.old_key})
SET d.source_obligation_id = m.source_id,
    d.target_obligation_id = m.target_id,
    d.key                  = m.new_key
RETURN count(d) AS repointed
"""

EXISTING_KEYS = """
UNWIND $keys AS key
MATCH (d:LinkDecision {key: key})
RETURN collect(d.key) AS present
"""


def read_obligation_statements(tx: ManagedTransaction, *, version_id: str) -> dict[str, str]:
    """One edition's obligations as `{obligation_id: normalized statement}`.

    Read *before* `drop_obligations`, because that is the only moment the old
    ids and their statements exist together: `:LinkDecision` stores no
    statement, and the obligation carrying it is about to be deleted.
    """
    return {
        record["obligation_id"]: normalize(record["statement"])
        for record in tx.run(READ_OBLIGATION_STATEMENTS, {"version_id": version_id})
    }


def repoint_decisions(
    tx: ManagedTransaction, *, before: dict[str, str], after: dict[str, str]
) -> int:
    """Carry recorded verdicts across a change of obligation identity (ADR-027).

    `before` maps each old obligation id to its normalized statement; `after`
    maps each normalized statement to the id the rebuild has just written for
    it. A statement that did not move produces the same id on both sides and is
    skipped.

    A decision whose new key already belongs to another decision is left
    exactly as it was. Merging two human verdicts into one is the single
    outcome this must not have, and an unrepaired decision is still counted by
    `replay_decisions` as `unpromotable`.
    """
    moved = {
        old_id: after[statement]
        for old_id, statement in before.items()
        if statement in after and after[statement] != old_id
    }
    if not moved:
        return 0

    decisions = list(tx.run(READ_DECISIONS_FOR, {"ids": list(moved)}))
    if not decisions:
        return 0

    proposed = []
    for record in decisions:
        source_id = moved.get(record["source_id"], record["source_id"])
        target_id = moved.get(record["target_id"], record["target_id"])
        new_key = decision_key(source_id, target_id)
        if new_key == record["key"]:
            continue
        proposed.append(
            {
                "old_key": record["key"],
                "new_key": new_key,
                "source_id": source_id,
                "target_id": target_id,
            }
        )
    if not proposed:
        return 0

    taken = set(
        tx.run(EXISTING_KEYS, {"keys": [m["new_key"] for m in proposed]}).single()["present"]
    )
    moves = [m for m in proposed if m["new_key"] not in taken]
    if not moves:
        return 0

    return tx.run(APPLY_REPOINT, {"moves": moves}).single()["repointed"]


def decision_key(source_id: str, target_id: str) -> str:
    """Identity for a verdict on one directed pair.

    Content-derived from two obligation ids, which are themselves content-derived
    (extraction.schema.obligation_id) — so the key survives a re-extraction that
    reproduces the same obligations. A key built from an internal node id would
    not: the node is dropped and recreated on every rebuild.

    Directional. "A implements B" is not "B implements A", and a symmetric key
    would let a verdict on one direction silently decide the other.
    """
    return hashlib.sha256(f"{source_id}|{target_id}".encode()).hexdigest()[:32]


def record_decision(
    tx: ManagedTransaction,
    *,
    source_id: str,
    target_id: str,
    verdict: str,
    actor: str,
    rationale: str,
) -> None:
    """Record one human verdict, replacing any earlier verdict on the same pair.

    Replacing rather than appending: a reviewer who changes their mind must leave
    one current verdict, not two contradictory records for a replay to choose
    between. The history that a control framework might want is not kept here —
    see ADR-014 on what `:LinkDecision`'s shape leaves open.
    """
    if verdict not in set(Verdict):
        raise ValueError(
            f"unknown verdict {verdict!r}; expected one of {[v.value for v in Verdict]}"
        )
    tx.run(
        RECORD_DECISION,
        {
            "key": decision_key(source_id, target_id),
            "source_id": source_id,
            "target_id": target_id,
            "verdict": verdict,
            "actor": actor,
            "rationale": rationale,
        },
    ).consume()


def replay_decisions(tx: ManagedTransaction) -> dict[str, int]:
    """Apply every recorded verdict to the graph. The sole writer of `IMPLEMENTS`.

    Returns `promoted`, `suppressed` and `unpromotable`. The third is the one a
    caller must not ignore: an approval whose obligations no longer exist after a
    re-extraction is still recorded, but the graph cannot express it, and a
    rebuild that reported only "promoted: 4" would look complete when a human
    decision had quietly stopped being represented.
    """
    unpromotable = tx.run(UNPROMOTABLE).single()["unpromotable"]
    promoted = tx.run(PROMOTE).single()["promoted"]
    suppressed = tx.run(SUPPRESS).single()["suppressed"]
    return {
        "promoted": promoted,
        "suppressed": suppressed,
        "unpromotable": unpromotable,
    }
