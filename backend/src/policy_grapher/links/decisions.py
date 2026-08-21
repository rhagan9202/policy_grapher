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
