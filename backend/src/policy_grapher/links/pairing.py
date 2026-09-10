"""Human verdicts on same-document pairings, and the edition-scoped reads.

`:PairingDecision` is **canonical**, exactly as `:LinkDecision` is: a verdict is
a thing a person did, and no rebuild may discard it (ADR-014). It answers the
other question, in the other vocabulary — not "does our clause discharge that
duty?" but "is the newer clause the reworded older one?" — which is why the
properties are `old_obligation_id`/`new_obligation_id` and never
`source`/`target`: those names belong to the implements question.

Nothing here writes `IMPLEMENTS`, `IMPLEMENTS_PROPOSED`, or `PAIRING_CANDIDATE`.
A pairing verdict takes effect inside the diff, which reads it through
`read_pairings`; the candidate edges are the diff's own derived record, written
and dropped in `changes/diff.py`.

Direction is older→newer, but that is not a property this module can promise:
`record_pairing` stores whatever ids it is given, and the key is a directional
hash of them. The one route that records verdicts orders the pair itself before
calling in — the obligation ids determine their editions, and the editions
order — so the promise is pinned at the route, not here.
"""

import hashlib
from enum import StrEnum

from neo4j import ManagedTransaction


class PairingVerdict(StrEnum):
    """Closed on purpose, for `decisions.Verdict`'s reason: the diff branches on
    this value when applying verdicts, and it matches each member explicitly, so
    one it does not recognise is claimed by neither arm — the pair stays
    unsettled and the diff keeps re-asking about it.

    That is the *safe* failure, and it is only safe because the branch is
    explicit. An `else` falling through to the pairing arm would apply an
    unrecognised verdict as a `paired` one and caption the row as a human
    decision, which is the same loss in the direction that puts words in a
    reviewer's mouth. `record_pairing` refuses to write a value outside this
    enum, so the two guards meet: nothing writes one, and nothing acts on one.
    """

    PAIRED = "paired"
    DISTINCT = "distinct"


RECORD = """
MERGE (d:PairingDecision {key: $key})
SET d.old_obligation_id = $old_id,
    d.new_obligation_id = $new_id,
    d.verdict           = $verdict,
    d.actor             = $actor,
    d.rationale         = $rationale,
    d.at                = datetime()
"""

# Scoped through :MANDATES to the two named editions, one obligation in each.
# The scope is the point: an obligation serves every diff its edition is in — a
# middle edition belongs to two pairs — so "any decision touching these
# obligations" would leak a neighbouring pair's verdict into this diff. The
# final inequality keeps out a decision recorded inside a single edition, which
# answers neither pair's question. Both reads below share this fragment so they
# can never disagree about which decisions belong to a pair of editions.
_SCOPE = """
MATCH (d:PairingDecision)
MATCH (old_v:DocumentVersion)-[:MANDATES]->
      (:Obligation {obligation_id: d.old_obligation_id})
MATCH (new_v:DocumentVersion)-[:MANDATES]->
      (:Obligation {obligation_id: d.new_obligation_id})
WHERE old_v.version_id IN [$from_version_id, $to_version_id]
  AND new_v.version_id IN [$from_version_id, $to_version_id]
  AND old_v.version_id <> new_v.version_id
"""

READ = _SCOPE + """
RETURN d.old_obligation_id AS old_id,
       d.new_obligation_id AS new_id,
       d.verdict           AS verdict
"""

# The same decisions with the actor kept: the queue lists settled pairs so a
# reviewer can reach one again to undo it, and who settled it is part of what
# they are undoing.
SETTLED = _SCOPE + """
RETURN d.old_obligation_id AS old_id,
       d.new_obligation_id AS new_id,
       d.verdict           AS verdict,
       d.actor             AS actor
"""

# A verdict whose obligation a re-extraction no longer produces. The decision
# stays — it is a fact a human established — but the diff cannot apply it, and
# a rebuild reporting only what it applied would look complete while a human
# decision had quietly stopped being represented. The true analogue of
# `decisions.UNPROMOTABLE`, counted beside it in the rebuild.
STRANDED = """
MATCH (d:PairingDecision)
WHERE NOT EXISTS { MATCH (:Obligation {obligation_id: d.old_obligation_id}) }
   OR NOT EXISTS { MATCH (:Obligation {obligation_id: d.new_obligation_id}) }
RETURN count(d) AS stranded
"""


def pairing_key(old_id: str, new_id: str) -> str:
    """Identity for a verdict on one ordered pair of clauses.

    Content-derived from two obligation ids, which are themselves
    content-derived, so the key survives a re-extraction that reproduces the
    same obligations. Directional, as `decisions.decision_key` is: the
    properties say which end is old, and a symmetric key would let a
    mis-ordered write replace a well-ordered verdict it does not match.
    """
    return hashlib.sha256(f"{old_id}|{new_id}".encode()).hexdigest()[:32]


def record_pairing(
    tx: ManagedTransaction,
    *,
    old_id: str,
    new_id: str,
    verdict: str,
    actor: str,
    rationale: str,
) -> None:
    """Record one human pairing verdict, replacing any earlier verdict on the
    same ordered pair.

    Replacing rather than appending, for `record_decision`'s reason: a reviewer
    who changes their mind must leave one current verdict, not two records for
    the diff to choose between. The MERGE is on `key`, and
    `pairing_decision_key_unique` (db.py) holds that to one node rather than a
    race to a second.
    """
    if verdict not in set(PairingVerdict):
        raise ValueError(
            f"unknown verdict {verdict!r}; expected one of "
            f"{[v.value for v in PairingVerdict]}"
        )
    tx.run(
        RECORD,
        {
            "key": pairing_key(old_id, new_id),
            "old_id": old_id,
            "new_id": new_id,
            "verdict": verdict,
            "actor": actor,
            "rationale": rationale,
        },
    ).consume()


def read_pairings(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> dict[tuple[str, str], str]:
    """The verdicts between two editions, as `{(old_id, new_id): verdict}`.

    Keys are as stored — canonical older→newer — whichever order the editions
    were named in, because Triage accepts arbitrary direction; a caller applying
    verdicts must look a pair up under both orientations.
    """
    return {
        (record["old_id"], record["new_id"]): record["verdict"]
        for record in tx.run(
            READ,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    }


def read_settled(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> list[dict]:
    """The same decisions with their actors, for the queue's settled list."""
    return [
        {
            "old_id": record["old_id"],
            "new_id": record["new_id"],
            "verdict": record["verdict"],
            "actor": record["actor"],
        }
        for record in tx.run(
            SETTLED,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    ]


def count_stranded_pairings(tx: ManagedTransaction) -> int:
    """Decisions the graph can no longer express: either obligation is gone."""
    return tx.run(STRANDED).single()["stranded"]
