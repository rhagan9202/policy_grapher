"""Convert the legacy same-document :LinkDecision into the pairing vocabulary.

Before the split, a pair of clauses inside one document could be proposed,
verdicted, and promoted as `IMPLEMENTS` — the pairing question wearing the
cross-document vocabulary. The design retires that state: `propose_links` skips
the pair, `record_decision` refuses it, and this module converts what the old
path already recorded (spec, Migration). A same-document `IMPLEMENTS` question
was only ever the pairing question in disguise — an edition does not discharge
its predecessor — so the migration recovers the judgement the reviewer actually
made rather than rewriting it.

Run at application startup, after `db.apply_schema`: the conversion MERGEs on
`:PairingDecision.key` and needs `pairing_decision_key_unique` in place first.
Idempotent by construction — everything a run converts or retires stops
matching the queries that found it, so a second run returns zeros. Import-
callable so the tests can drive it directly.

ADR-014 is the constraint the shape answers to: no rebuild — and no schema
change — may discard a decision. Nothing here deletes a `:LinkDecision`. A
decision leaves the live label by *retirement*, relabelled
`:RetiredLinkDecision` with every property intact plus a `retired_reason`,
because a same-document decision left under `:LinkDecision` with
`verdict: 'approve'` is matched by `PROMOTE` — which has no document predicate
— on every review POST and every rebuild, resurrecting its edge indefinitely
into Ask's undirected traversal, which no shipped guard reaches.
"""

from collections import Counter

from neo4j import Driver, ManagedTransaction

from policy_grapher.links.pairing import PairingVerdict, pairing_key

# Decisions whose obligations BOTH still exist and resolve through one
# :Document. A decision only one side of which resolves is not this migration's
# business — it is `unpromotable`/`rejections_stranded`, and retiring it here
# would destroy the repair `repoint_decisions` may yet make.
#
# The ordering columns come back as strings on purpose: `toString` of a Neo4j
# datetime is ISO-8601, which sorts lexically as it sorts temporally, and
# `coalesce` to '' keeps an unset date or ingest timestamp comparable instead
# of None-poisoning the Python sort. `effective_date` is already stored as an
# ISO string (versions.py), so `toString` is identity there.
SAME_DOCUMENT_DECISIONS = """
MATCH (d:LinkDecision)
MATCH (source:Obligation {obligation_id: d.source_obligation_id})
MATCH (target:Obligation {obligation_id: d.target_obligation_id})
MATCH (doc:Document)-[:HAS_VERSION]->(sv:DocumentVersion)-[:MANDATES]->(source)
MATCH (doc)-[:HAS_VERSION]->(tv:DocumentVersion)-[:MANDATES]->(target)
RETURN d.key AS key,
       d.verdict AS verdict,
       d.source_obligation_id AS source_id,
       d.target_obligation_id AS target_id,
       sv.version_id AS source_version,
       coalesce(toString(sv.effective_date), '') AS source_effective,
       coalesce(toString(sv.ingested_at), '') AS source_ingested,
       tv.version_id AS target_version,
       coalesce(toString(tv.effective_date), '') AS target_effective,
       coalesce(toString(tv.ingested_at), '') AS target_ingested
"""

# Retirement: the label moves, the node stays. REMOVE :LinkDecision is the
# entire idempotency mechanism — a retired node stops matching the read above —
# and it is what takes the decision out of PROMOTE's match. The promoted edge
# goes in the same statement, because SUPPRESS deletes only for `reject` and
# nothing else would ever take an approved same-document IMPLEMENTS away.
RETIRE = """
UNWIND $keys AS key
MATCH (d:LinkDecision {key: key})
SET d:RetiredLinkDecision, d.retired_reason = $reason
REMOVE d:LinkDecision
WITH d
OPTIONAL MATCH (:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(DISTINCT d) AS retired
"""

# Conversion carries the judgement, not the shape: the verdict is re-mapped by
# the caller, actor/rationale/at copied verbatim, and the pair re-oriented
# before the key is computed — `key` is a directional hash, so a mis-oriented
# node carries one no pairings POST ever computes, and a re-verdict would MERGE
# a second decision beside it instead of replacing it. MERGE, not CREATE, for
# the same reason `record_pairing` MERGEs: one pair, one node, one key — which
# also collapses the degenerate find of the same pair verdicted in both
# directions onto a single node, last row winning.
CONVERT = """
UNWIND $conversions AS c
MATCH (d:LinkDecision {key: c.old_key})
MERGE (p:PairingDecision {key: c.new_key})
SET p.old_obligation_id = c.old_id,
    p.new_obligation_id = c.new_id,
    p.verdict           = c.verdict,
    p.actor             = d.actor,
    p.rationale         = d.rationale,
    p.at                = d.at
SET d:RetiredLinkDecision, d.retired_reason = 'converted'
REMOVE d:LinkDecision
WITH d
OPTIONAL MATCH (:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(DISTINCT d) AS converted
"""

# Derived, undecidable after the recorder's guard, and matched by the review
# queue with no document predicate: left "to lapse on the next rebuild" these
# would sit in the queue forever with `pending` inflated and no verdict able to
# clear them. Scoped through one :Document — a cross-document proposal is live
# inventory and must survive.
DELETE_SAME_DOCUMENT_PROPOSALS = """
MATCH (a:Obligation)-[r:IMPLEMENTS_PROPOSED]->(b:Obligation)
MATCH (doc:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(a)
MATCH (doc)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(b)
DELETE r
"""

# `record_decision` closed the verdict vocabulary long before this module
# existed, so a value outside this mapping is corruption. It is retired rather
# than raised on — see the `unknown_verdict` branch below for why the usual
# loud failure is the wrong one at this particular call site.
_VERDICT = {
    "approve": PairingVerdict.PAIRED.value,
    "reject": PairingVerdict.DISTINCT.value,
}


def _migrate(tx: ManagedTransaction) -> dict[str, int]:
    rows = list(tx.run(SAME_DOCUMENT_DECISIONS))

    same_edition: list[str] = []
    unknown_verdict: list[str] = []
    convertible: list[dict] = []
    for row in rows:
        if row["source_version"] == row["target_version"]:
            # Answers neither vocabulary's question and cannot be oriented:
            # two clauses of one edition have no older or newer side. Checked
            # before the verdict because it is the stronger fact: a
            # same-edition decision was never going to have its verdict
            # mapped, whatever that verdict says.
            same_edition.append(row["key"])
            continue
        if row["verdict"] not in _VERDICT:
            # A value `record_decision` could not have written, so the node is
            # corrupt — and raising here would be the wrong loud failure. This
            # module runs inside `lifespan`, so an exception makes the whole
            # application unstartable over one node, and everything that could
            # diagnose or rescue the graph — the admin routes, the export the
            # Reset screen calls the only copy — is behind the process that
            # will not start. Retired with the other classes it cannot map
            # instead: counted, logged at boot, and permanently out of
            # `PROMOTE`'s match rather than merely outside it by luck of the
            # `verdict: 'approve'` filter.
            unknown_verdict.append(row["key"])
            continue
        source_order = (
            row["source_effective"],
            row["source_ingested"],
            row["source_version"],
        )
        target_order = (
            row["target_effective"],
            row["target_ingested"],
            row["target_version"],
        )
        # The corpus ordering rule — (coalesce(effective_date, ''),
        # ingested_at, version_id) — including the version_id tie-breaker this
        # feature adds: two undated editions ingested in one instant otherwise
        # tie, and neither orientation could be called older. The one live
        # decision this migration was written for ran newer→older (its
        # same-document proposal promoted that way), and canonical
        # :PairingDecision runs older→newer, so the pair is re-oriented, not
        # copied; both orientations occur in the wild and both are handled.
        if source_order < target_order:
            old_id, new_id = row["source_id"], row["target_id"]
            editions = (row["source_version"], row["target_version"])
        else:
            old_id, new_id = row["target_id"], row["source_id"]
            editions = (row["target_version"], row["source_version"])
        convertible.append(
            {
                "old_key": row["key"],
                "new_key": pairing_key(old_id, new_id),
                "old_id": old_id,
                "new_id": new_id,
                "verdict": _VERDICT[row["verdict"]],
                "editions": editions,
            }
        )

    # Two convertible approvals sharing an endpoint within one edition pair
    # would convert into exactly the two-live-`paired`-verdicts state the
    # pairings POST's 409 exists to refuse — minted by a writer that route
    # does not guard. Neither converts; the reviewer re-records the one they
    # mean through the route, which enforces the conflict rule. Scoped per
    # edition pair on purpose: a middle edition's clause paired into both
    # adjacent pairs is legitimate and passes. `distinct` verdicts never
    # conflict — the 409 refuses only a second live `paired`.
    paired_endpoints: Counter = Counter()
    for candidate in convertible:
        if candidate["verdict"] != PairingVerdict.PAIRED.value:
            continue
        paired_endpoints[(candidate["editions"], candidate["old_id"])] += 1
        paired_endpoints[(candidate["editions"], candidate["new_id"])] += 1
    conflicting_keys = {
        candidate["old_key"]
        for candidate in convertible
        if candidate["verdict"] == PairingVerdict.PAIRED.value
        and (
            paired_endpoints[(candidate["editions"], candidate["old_id"])] > 1
            or paired_endpoints[(candidate["editions"], candidate["new_id"])] > 1
        )
    }
    conversions = [
        {
            "old_key": candidate["old_key"],
            "new_key": candidate["new_key"],
            "old_id": candidate["old_id"],
            "new_id": candidate["new_id"],
            "verdict": candidate["verdict"],
        }
        for candidate in convertible
        if candidate["old_key"] not in conflicting_keys
    ]

    implements_deleted = 0
    retired_same_edition = 0
    if same_edition:
        result = tx.run(RETIRE, {"keys": same_edition, "reason": "same_edition"})
        retired_same_edition = result.single()["retired"]
        implements_deleted += result.consume().counters.relationships_deleted

    retired_unknown_verdict = 0
    if unknown_verdict:
        result = tx.run(
            RETIRE, {"keys": unknown_verdict, "reason": "unknown_verdict"}
        )
        retired_unknown_verdict = result.single()["retired"]
        implements_deleted += result.consume().counters.relationships_deleted

    retired_conflicting = 0
    if conflicting_keys:
        result = tx.run(
            RETIRE,
            {"keys": sorted(conflicting_keys), "reason": "conflicting_pairing"},
        )
        retired_conflicting = result.single()["retired"]
        implements_deleted += result.consume().counters.relationships_deleted

    converted = 0
    if conversions:
        result = tx.run(CONVERT, {"conversions": conversions})
        converted = result.single()["converted"]
        implements_deleted += result.consume().counters.relationships_deleted

    proposals_deleted = (
        tx.run(DELETE_SAME_DOCUMENT_PROPOSALS)
        .consume()
        .counters.relationships_deleted
    )

    return {
        "converted": converted,
        "retired_same_edition": retired_same_edition,
        "retired_conflicting": retired_conflicting,
        "retired_unknown_verdict": retired_unknown_verdict,
        "implements_deleted": implements_deleted,
        "proposals_deleted": proposals_deleted,
    }


def migrate_pairing_decisions(driver: Driver, database: str) -> dict[str, int]:
    """Convert, retire and clean up in one transaction; return the five counts.

    One transaction on purpose: a conversion that landed without its
    retirement would leave a decision `PROMOTE` still matches, and the next
    replay would resurrect the very edge the conversion just deleted. Keys:

    - `converted` — same-document decisions re-recorded as `:PairingDecision`,
      re-oriented older→newer by the corpus rule.
    - `retired_same_edition` — decisions between two clauses of one edition.
    - `retired_conflicting` — approvals sharing an endpoint within one edition
      pair; the reviewer re-records the survivor through the pairings route.
    - `retired_unknown_verdict` — decisions carrying a verdict no vocabulary
      recognises. Non-zero means corruption and is worth investigating, but it
      does not stop the run: raising inside `lifespan` would cost the whole
      application over one node.
    - `implements_deleted` — promoted same-document edges removed with their
      decisions.
    - `proposals_deleted` — same-document `IMPLEMENTS_PROPOSED` edges removed.

    A second run returns zeros: nothing a run converts or retires still
    matches the queries that found it.
    """
    with driver.session(database=database) as session:
        return session.execute_write(_migrate)
