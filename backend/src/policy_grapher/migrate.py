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

# Decisions whose obligations both exist but do not both resolve through a
# `:Document`. Every other query in this module routes through `:Document`, so
# these are invisible to all of them, and a same-document one among them stays
# under `:LinkDecision` — where only `PROMOTE`'s own document predicate now
# stops its edge coming back (links/decisions.py). `delete_document` produces the
# state: it removes the document, its versions and their chunks, and leaves the
# obligations behind (documents.py).
#
# Counted, never touched. Without documents there is no way to tell a
# same-document verdict from a cross-document one, and retiring a legitimate
# implements verdict would be this migration's own data loss. The repair is
# deletion cascading to obligations, which is a different story; what belongs
# here is that a run cannot report a graph clean when part of it was unreadable.
DECISIONS_MISSING_DOCUMENTS = """
MATCH (d:LinkDecision)
MATCH (source:Obligation {obligation_id: d.source_obligation_id})
MATCH (target:Obligation {obligation_id: d.target_obligation_id})
WHERE NOT EXISTS {
        MATCH (:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(source)
      }
   OR NOT EXISTS {
        MATCH (:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(target)
      }
RETURN count(d) AS missing
"""

# Decisions one of whose obligation NODES is gone entirely. Counted because
# every other query here — including the census above — opens by matching both
# obligations, so a decision missing one is invisible to all of them: not
# converted, not retired, and, until this existed, not reported either. A run
# returned eight zeros over a graph holding a same-document `approve` it could
# not see.
#
# Untouched, like the census above, and for a stronger reason: this is the class
# `repoint_decisions` exists to repair, and `unpromotable`/`rejections_stranded`
# report on the rebuild path. Retiring one here would destroy a repair the next
# rebuild may yet make. What it buys is that the boot's counts stop reading as a
# clean graph, and that is all it is for — the same-document edge such a decision
# could resurrect is refused at `PROMOTE` itself (links/decisions.py), not here.
DECISIONS_MISSING_OBLIGATIONS = """
MATCH (d:LinkDecision)
WHERE NOT EXISTS { MATCH (:Obligation {obligation_id: d.source_obligation_id}) }
   OR NOT EXISTS { MATCH (:Obligation {obligation_id: d.target_obligation_id}) }
RETURN count(d) AS missing
"""

# Every `:PairingDecision` already in the graph, with its editions where they
# can still be resolved. Two screens read this, and they need different halves
# of it:
#
# - `key` is read for ALL of them, resolvable or not, because `CONVERT` MERGEs
#   on that key and would overwrite whatever holds it. A stranded pairing
#   decision — one whose obligations a re-extraction moved — is exactly as
#   destructible as a live one, so the OPTIONAL MATCHes must not filter it out.
# - the endpoints and editions are read only for live `paired` verdicts, to
#   carry the conflict rule across runs. `old_obligation_id` is in the older
#   edition by construction, so `(old_version, new_version)` lines up with the
#   edition tuple the classifier builds; a mis-ordered decision produces a tuple
#   that matches no candidate, which is a miss rather than a false conflict.
EXISTING_PAIRINGS = """
MATCH (p:PairingDecision)
OPTIONAL MATCH (old_v:DocumentVersion)-[:MANDATES]->
               (:Obligation {obligation_id: p.old_obligation_id})
OPTIONAL MATCH (new_v:DocumentVersion)-[:MANDATES]->
               (:Obligation {obligation_id: p.new_obligation_id})
RETURN p.key AS key,
       p.verdict AS verdict,
       p.old_obligation_id AS old_id,
       p.new_obligation_id AS new_id,
       old_v.version_id AS old_version,
       new_v.version_id AS new_version
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
# node carries one the route that records pairing verdicts would never compute
# (spec §6), and a re-verdict there would MERGE a second decision beside it
# instead of replacing it.
#
# **This statement overwrites whatever holds `c.new_key`.** The MERGE finds an
# existing node by key and the SET below is unconditional, so a key already
# claimed — by a `:PairingDecision` in the graph, or by an earlier row of this
# same batch — has its verdict, actor, rationale and timestamp replaced, and
# the replacement is silent. `UNWIND` has no defined row order and
# `SAME_DOCUMENT_DECISIONS` has no ORDER BY, so which human's verdict survives
# would not even be deterministic.
#
# It is safe only because the caller screens every row first: no two rows here
# share a `new_key`, and no `new_key` belongs to a decision that already
# exists. Those screens are load-bearing, not defensive — do not relax one
# without replacing it.
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
WITH d, p
OPTIONAL MATCH (:Obligation {obligation_id: d.source_obligation_id})
              -[r:IMPLEMENTS]->
              (:Obligation {obligation_id: d.target_obligation_id})
DELETE r
RETURN count(DISTINCT p) AS converted
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

    existing = list(tx.run(EXISTING_PAIRINGS)) if convertible else []

    # Screen 1, against the graph: a conversion whose key another decision
    # already holds must not convert, because `CONVERT` would MERGE onto that
    # node and overwrite a verdict, an actor and a rationale that a person put
    # there. Not this migration's to replace — retired instead, so the legacy
    # verdict stays readable under the archival label and a reviewer can settle
    # the disagreement themselves.
    #
    # This is `repoint_decisions`' rule (links/decisions.py), which faces the
    # same hazard and answers it the same way: a decision whose new key already
    # belongs to another is left as it was rather than merged over it.
    taken_keys = {row["key"] for row in existing}
    pairing_exists_keys = {
        candidate["old_key"]
        for candidate in convertible
        if candidate["new_key"] in taken_keys
    }

    # Screen 2, the conflict rule, in two halves that are one rule.
    #
    # (a) Two candidates computing ONE key are two verdicts on one pair, written
    # in opposite orientations — reachable because the pre-guard `propose_links`
    # wrote proposals org→candidate, so rebuilding X against Y and later Y
    # against X produced both directions and each was independently reviewable.
    # They cannot both be recorded and neither may be chosen, so both retire.
    # Detected by key rather than by endpoint on purpose: the endpoint half
    # below counts `paired` verdicts only, so a `paired`/`distinct` disagreement
    # on one pair passes it untouched — and widening that half to every verdict
    # would wrongly refuse a legitimate `paired` on (X,Y) beside a `distinct` on
    # (X,Z), which share an endpoint and must both convert.
    #
    # (b) Two `paired` verdicts naming one clause within one edition pair are
    # the state the pairing route refuses with a 409 (routers/pairings.py) —
    # and this writer is not behind that route, so the rule holds here on its
    # own.
    # Scoped per edition pair, so a middle edition's clause paired into both
    # adjacent pairs is legitimate and passes. `distinct` verdicts never
    # conflict — only a second live `paired` does. The already-recorded
    # decisions are counted alongside the candidates, which is what makes the
    # rule hold across runs as well as within one: a decision arriving between
    # two boots would otherwise convert beside a `paired` verdict an earlier
    # boot had already minted on the same clause.
    key_claims: Counter = Counter(
        candidate["new_key"] for candidate in convertible
    )
    paired_endpoints: Counter = Counter()
    for row in existing:
        if row["verdict"] != PairingVerdict.PAIRED.value:
            continue
        if row["old_version"] is None or row["new_version"] is None:
            continue
        editions = (row["old_version"], row["new_version"])
        paired_endpoints[(editions, row["old_id"])] += 1
        paired_endpoints[(editions, row["new_id"])] += 1
    for candidate in convertible:
        if candidate["verdict"] != PairingVerdict.PAIRED.value:
            continue
        paired_endpoints[(candidate["editions"], candidate["old_id"])] += 1
        paired_endpoints[(candidate["editions"], candidate["new_id"])] += 1
    conflicting_keys = {
        candidate["old_key"]
        for candidate in convertible
        if candidate["old_key"] not in pairing_exists_keys
        and (
            key_claims[candidate["new_key"]] > 1
            or (
                candidate["verdict"] == PairingVerdict.PAIRED.value
                and (
                    paired_endpoints[(candidate["editions"], candidate["old_id"])] > 1
                    or paired_endpoints[(candidate["editions"], candidate["new_id"])] > 1
                )
            )
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
        and candidate["old_key"] not in pairing_exists_keys
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

    retired_pairing_exists = 0
    if pairing_exists_keys:
        result = tx.run(
            RETIRE,
            {"keys": sorted(pairing_exists_keys), "reason": "pairing_exists"},
        )
        retired_pairing_exists = result.single()["retired"]
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

    # Disjoint from everything above by construction, not by ordering: a
    # decision is retired only if `SAME_DOCUMENT_DECISIONS` found it, which
    # requires both obligations to resolve through one `:Document`, and this
    # counts only those where at least one does not. So it is always a census
    # of what the run could not see, never a second count of what it just did.
    missing_documents = tx.run(DECISIONS_MISSING_DOCUMENTS).single()["missing"]
    missing_obligations = tx.run(DECISIONS_MISSING_OBLIGATIONS).single()["missing"]

    return {
        "converted": converted,
        "retired_same_edition": retired_same_edition,
        "retired_conflicting": retired_conflicting,
        "retired_unknown_verdict": retired_unknown_verdict,
        "retired_pairing_exists": retired_pairing_exists,
        "implements_deleted": implements_deleted,
        "proposals_deleted": proposals_deleted,
        "decisions_missing_documents": missing_documents,
        "decisions_missing_obligations": missing_obligations,
    }


def migrate_pairing_decisions(driver: Driver, database: str) -> dict[str, int]:
    """Convert, retire and clean up in one transaction; return the counts.

    One transaction on purpose: a conversion that landed without its
    retirement would leave a decision `PROMOTE` still matches, and the next
    replay would resurrect the very edge the conversion just deleted. Keys:

    - `converted` — `:PairingDecision` nodes minted, re-oriented older→newer by
      the corpus rule. Counted over the nodes written rather than over the
      decisions retired, so that the two numbers disagree loudly if a screen
      below ever stops holding and two originals collapse onto one node.
    - `retired_same_edition` — decisions between two clauses of one edition.
    - `retired_conflicting` — two verdicts the migration must not choose
      between: two decisions on one pair written in opposite orientations, or
      two `paired` verdicts naming one clause within one edition pair. A person
      re-records the one they mean through the pairing route, which enforces the
      same conflict rule (routers/pairings.py).
    - `retired_unknown_verdict` — decisions carrying a verdict no vocabulary
      recognises. Non-zero means corruption and is worth investigating, but it
      does not stop the run: raising inside `lifespan` would cost the whole
      application over one node.
    - `retired_pairing_exists` — decisions whose pair a `:PairingDecision`
      already answers. Converting would overwrite that verdict, actor and
      rationale silently; the legacy one is retired unread instead.
    - `implements_deleted` — promoted same-document edges removed with their
      decisions.
    - `proposals_deleted` — same-document `IMPLEMENTS_PROPOSED` edges removed.
    - `decisions_missing_documents` — decisions this run could not classify
      because their obligations no longer resolve to a `:Document`, the state
      `DELETE /documents/{slug}` leaves behind. Reported, never touched: without
      documents there is no way to tell a same-document verdict from a
      cross-document one, and retiring a legitimate implements verdict would be
      this migration's own data loss. `main.lifespan` logs it at WARNING rather
      than leaving it in the dict.
    - `decisions_missing_obligations` — decisions one of whose obligation *nodes*
      is gone. Every other query here matches both obligations, so such a
      decision is converted by nothing, retired by nothing, and was reported by
      nothing: a run returned eight zeros over a graph that still held a
      same-document `approve`. Reported, never touched — this is the class
      `repoint_decisions` repairs and `unpromotable`/`rejections_stranded` report
      on the rebuild path, so retiring it here would destroy a repair that is
      still possible. It carries no WARNING of its own for that reason: unlike
      the census above it has an owner and a routine cause, and a line printed
      on every boot of a graph with one stranded verdict is a line readers learn
      to skip.

    **The two censuses' zeros are load-bearing together**, and neither alone:
    between them they cover every `:LinkDecision` this run's conversion query
    could not read, so two zeros are what make the other six counts a complete
    account. Non-zero in either means the graph may still hold a same-document
    decision the migration could not classify — which `PROMOTE`'s document
    predicate keeps from becoming an `IMPLEMENTS` edge (links/decisions.py),
    while the next boot converts it once the missing node or document is back.

    A second run returns zeros: nothing a run converts or retires still
    matches the queries that found it. The two censuses are the exception and
    report the same number every boot, because they are censuses rather than
    units of work.
    """
    with driver.session(database=database) as session:
        return session.execute_write(_migrate)
