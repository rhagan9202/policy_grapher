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
`record_pairing` stores the ids in the order it is given them, and the key is a
directional hash of them. The one route that records verdicts orders the pair
itself before calling in — the obligation ids determine their editions, and the
editions order — so the promise is pinned at the route, not here.

What this module *does* refuse is a pair drawn from two different documents,
mirroring `record_decision`'s same-document refusal: neither question is
answerable in the other's vocabulary, and a rule the route alone enforced would
be a rule only one caller obeys.
"""

import hashlib
from enum import StrEnum

from neo4j import ManagedTransaction

from policy_grapher.links.decisions import DecisionSchema


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


# Positive evidence that the two clauses are drawn from two different
# documents, read in the transaction the verdict would land in. Phrased as
# "I can see two documents and they differ", never as "I cannot see one
# document" — the second refuses every pair whose obligations a re-extraction
# has stranded, and a `:PairingDecision` outlives its obligations by design
# (`repoint_decisions` repairs them, `count_stranded_pairings` counts them), so
# that phrasing would make a stranded verdict unrecordable and un-reversible.
# `record_decision`'s SAME_DOCUMENT is the mirror of this and is deliberately
# built the same way round.
CROSS_DOCUMENT = """
MATCH (old_doc:Document)-[:HAS_VERSION]->(:DocumentVersion)
      -[:MANDATES]->(:Obligation {obligation_id: $old_id})
MATCH (new_doc:Document)-[:HAS_VERSION]->(:DocumentVersion)
      -[:MANDATES]->(:Obligation {obligation_id: $new_id})
WHERE old_doc <> new_doc
RETURN old_doc.slug AS old_slug, new_doc.slug AS new_slug
LIMIT 1
"""

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
       d.actor             AS actor,
       d.rationale         AS rationale
"""

# A verdict the diff can no longer apply. The decision stays — it is a fact a
# human established — but a caller reporting only what it applied would look
# complete while a human decision had quietly stopped being represented.
#
# The condition is the exact complement of `_SCOPE`'s join, and that is what makes
# it mean "unreachable" rather than "one node is missing". An obligation a
# re-extraction no longer produces strands a verdict, and so does an obligation
# that outlived its edition: `delete_document` removes the document, its versions
# and their chunks and leaves the obligations behind, after which `_SCOPE` matches
# nothing and both reads return empty while the obligations still exist. Checking
# obligation existence alone reported that state as zero — a verdict silently
# stopped applying with every count saying there was nothing to say.
STRANDED = """
MATCH (d:PairingDecision)
WHERE NOT EXISTS {
        MATCH (:DocumentVersion)-[:MANDATES]->
              (:Obligation {obligation_id: d.old_obligation_id})
      }
   OR NOT EXISTS {
        MATCH (:DocumentVersion)-[:MANDATES]->
              (:Obligation {obligation_id: d.new_obligation_id})
      }
RETURN count(d) AS stranded
"""

# The write lock that makes the pairing route's conflict check mean anything.
#
# Neo4j is read-committed and takes no locks for reads, and two verdicts on one
# clause MERGE two *different* `:PairingDecision` nodes — so there is no node
# the two transactions share, nothing for either to block on, and both conflict
# reads return nothing. Reproduced with two barriered sessions before this
# existed: both returned 200 and the graph was left holding two live `paired`
# verdicts on one clause, which is the state `changes/diff.py` says it cannot
# arbitrate. Co-locating the read with the write does not help, and neither
# does re-reading after it: both transactions stay blind to the other's
# uncommitted writes right up to commit.
#
# One node per *edition pair*, which is the scope the one-to-one rule itself has
# — coarser than the conflict, deliberately. A single lock cannot deadlock,
# where a lock per (clause, other edition) would need a total acquisition order
# to be sure of it, and the cost is that two reviewers settling unrelated pairs
# between the same two editions serialise. This is a human-driven review screen;
# that is not a cost worth a deadlock argument.
#
# The `SET` is load-bearing, not bookkeeping. A MERGE that *matches* need not
# take an exclusive lock on what it found, so without a write to the node the
# second transaction would sail past. `pairing_lock_key_unique` (db.py) is the
# other half: a bare MERGE under concurrency can create two nodes for one key,
# and two transactions locking two different nodes is the race back again.
ACQUIRE_PAIR_LOCK = """
MERGE (lock:PairingLock {key: $key})
SET lock.edition_pair = $edition_pair,
    lock.at           = datetime()
"""


class CrossDocumentPair(ValueError):
    """`record_pairing` refusing a pair drawn from two `:Document`s.

    The mirror of `decisions.SameDocumentPair`, and a type for its reason: the
    route has to tell a refusal it can explain to a person from a fault it
    cannot. The driver raises a bare `ValueError` out of `execute_write` when a
    parameter cannot be packed, so an `except ValueError` in the route would
    answer a serialisation bug of ours with "these two clauses are in different
    documents" — a 400 blaming a reviewer's data, and one that sends them to
    the wrong screen.

    Subclasses `ValueError` so nothing that already catches or expects one has
    to change.
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


def pairing_lock_key(old_version_id: str, new_version_id: str) -> str:
    """Identity for one edition pair's verdict lock.

    Built from the two editions in canonical older→newer order, so every caller
    settling a pair between them computes the same key and therefore takes the
    same lock. Hashed for `pairing_key`'s reason and not for secrecy: a
    `version_id` is user-supplied text, and a fixed-width key keeps the
    uniqueness constraint's index predictable.
    """
    return hashlib.sha256(
        f"pair-lock|{old_version_id}|{new_version_id}".encode()
    ).hexdigest()[:32]


def lock_edition_pair(
    tx: ManagedTransaction, *, old_version_id: str, new_version_id: str
) -> None:
    """Take the edition pair's write lock, held until this transaction ends.

    Must be called *before* the conflict check it protects, and in the same
    transaction as the write: the lock is what makes the second of two
    concurrent verdicts read the first one's committed decision rather than an
    empty result. Nothing about the lock node is ever read back — its only
    property is being locked.
    """
    tx.run(
        ACQUIRE_PAIR_LOCK,
        {
            "key": pairing_lock_key(old_version_id, new_version_id),
            "edition_pair": f"{old_version_id}|{new_version_id}",
        },
    ).consume()


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

    A pair drawn from two documents is refused. "Is the newer clause the older
    one reworded?" is a question about one instrument's editions; between two
    instruments the question is implementation, and it has its own canonical
    node. The refusal lives here and not only in the route for
    `record_decision`'s reason: a rule enforced at one caller is a rule only
    that caller obeys, and "nothing currently offers such a pair" is a fact
    about today's callers rather than a constraint. Membership beyond this —
    that the two editions differ, and which is older — stays the route's,
    because only the route can act on the answer.
    """
    if verdict not in set(PairingVerdict):
        raise ValueError(
            f"unknown verdict {verdict!r}; expected one of "
            f"{[v.value for v in PairingVerdict]}"
        )
    cross_document = tx.run(
        CROSS_DOCUMENT, {"old_id": old_id, "new_id": new_id}
    ).single()
    if cross_document is not None:
        raise CrossDocumentPair(
            f"{old_id!r} and {new_id!r} are mandated by editions of "
            f"{cross_document['old_slug']!r} and "
            f"{cross_document['new_slug']!r}. A pairing runs between two "
            "editions of one document — whether one document's clause "
            "discharges another's is the implements question, and it is "
            "answered on the Review screen."
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
            # Never None to the caller. A decision can have no `rationale`
            # property at all: `migrate.CONVERT` copies it off the
            # `:LinkDecision` it converts, and a SET to null removes the
            # property rather than storing one. `PairingSettledOut.rationale` is
            # a `str`, so the None would fail validation and take the whole
            # settled list down with it.
            "rationale": record["rationale"] or "",
        }
        for record in tx.run(
            SETTLED,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    ]


def count_stranded_pairings(tx: ManagedTransaction) -> int:
    """Decisions the diff can no longer apply: an obligation one of them names is
    gone, or is no longer `:MANDATES`-ed by any edition.

    Graph-wide, with no edition scope — a caller reporting it must not present it
    as its own run's loss. There is no cheaper honest answer: a verdict is
    stranded precisely when the join every read makes fails, and that join is
    what would have told you which editions it belonged to.
    """
    return tx.run(STRANDED).single()["stranded"]


# The pairing half of the repoint refactor (spec §5). Defined here rather than
# in links/decisions.py so that module never has to know pairing exists: the
# shared shape lives with the machinery, and each vocabulary names its own
# instance beside its own key function.
PAIRING_SCHEMA = DecisionSchema(
    label="PairingDecision",
    source_prop="old_obligation_id",
    target_prop="new_obligation_id",
    key_of=pairing_key,
)
