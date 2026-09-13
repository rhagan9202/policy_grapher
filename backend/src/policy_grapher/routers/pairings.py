"""Settling the pairs the diff declines — and undoing the ones it guessed.

Two routes. The GET runs the diff itself, exactly as Triage does:
`diff_versions`' only other caller is the Triage GET handler, so a queue that
merely read candidate edges would be empty for any edition pair nobody had
opened in Triage, and a verdict would take effect only the next time someone
loaded that screen. It inherits the same "a GET writes derived nodes" trade
Triage already flags and accepts (routers/triage.py, ADR-015).

The GET also pins direction, because nothing beneath it does — `diff_versions`
binds whatever from/to it is given, and `:Change`'s `FROM_VERSION`/`TO_VERSION`
carry request order, not chronology. A reversed pair here would quietly write
reversed candidate edges and serve a reviewer a queue whose question is upside
down, so it is a 400 instead. Triage keeps its arbitrary-direction behaviour;
its reversed runs' edges are cleaned by the undirected drop inside the diff.

The POST needs no recorded candidate edge. Admissibility is membership — both
obligations exist and are `:MANDATES`-ed by two editions of one document —
which deliberately departs from the review queue's proposal-gated rule
(routers/review.py): the pairing question exists for every pair of clauses in
the two editions, and gating on a candidate would make the recorder outrank the
person for exactly the declines this screen exists to reach — the silent
`score_pair` exclusions and the sub-threshold pairs the recording bound drops.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.changes.diff import OUTCOMES, diff_versions
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.links.pairing import (
    CrossDocumentPair,
    PairingVerdict,
    lock_edition_pair,
    read_settled,
    record_pairing,
)
from policy_grapher.models import (
    ObligationCitationOut,
    PairingCandidateOut,
    PairingQueueOut,
    PairingSettledOut,
    PairingVerdictIn,
    PairingVerdictOut,
)
from policy_grapher.obligations import primary_anchor

router = APIRouter(prefix="/pairings", tags=["pairings"])

VERSION_EXISTS = """
MATCH (v:DocumentVersion {version_id: $version_id}) RETURN count(v) AS total
"""

# The corpus ordering rule as a tuple this route can compare in Python:
# effective date, then ingest time, then version id. The version_id tie-breaker
# is this feature's addition — two undated editions ingested in one instant
# otherwise tie, and neither orientation of the pair would pass the 400 below.
# Strings throughout, and `toString` on every leg: the ISO form orders
# lexically, and coalescing absent values to '' keeps a fixture-built edition
# comparable at all. `effective_date` is an ISO string today
# (versions.merge_version), so `toString` is a no-op on it — which is the
# point. `migrate.py` reads all three legs through `toString`, and the two must
# agree by construction rather than by both happening to meet a string: the day
# any path stores a real temporal type, an unwrapped read here would compare a
# `Date` against `''` and order the pair differently from the migration. That
# disagreement is silent and expensive, because `pairing_key` is a directional
# hash — a pair the migration canonicalised one way and this route the other
# keys to two nodes, so a re-verdict sits beside the old decision instead of
# replacing it.
#
# The document is read here too, so the queue can refuse a cross-document pair
# before the diff writes anything. See `queue`.
ORDERING = """
UNWIND [$from_version_id, $to_version_id] AS wanted
MATCH (doc:Document)-[:HAS_VERSION]->(v:DocumentVersion {version_id: wanted})
RETURN v.version_id                              AS version_id,
       doc.slug                                  AS document_slug,
       coalesce(toString(v.effective_date), '')  AS effective_date,
       coalesce(toString(v.ingested_at), '')     AS ingested_at
"""

# One citation per side; see `obligations.primary_anchor` for why the anchor is
# not matched directly. The candidate edge is matched *directed* here, unlike
# the diff's drop: this route has already refused any pair that is not
# older→newer, and `diff_versions` has just dropped and rewritten this pair's
# edges from-side→to-side inside the same transaction, so every surviving edge
# runs with the request.
#
# `$outcome` is what makes a decline reachable, and the ordering below is why it
# has to exist. Everything at or above `PAIRING_CONFIDENCE` is recorded
# unconditionally (changes/diff.py), and a declined pair is *by construction* at
# or below the confidence of whatever beat it: `partner_taken` scores no higher
# than the winner that consumed its endpoint, `contested` sits within
# `PAIRING_MARGIN` of its rival, and `below_threshold` is under the bar
# altogether. So `confidence DESC` with a page cap cuts the declines first, and
# on a heavily reworded edition pair — hundreds of candidates from one cross
# product — the page holds nothing but pairs the diff already made. Filtering by
# outcome gives each class its own page; `$outcome IS NULL` keeps the unfiltered
# view, which is still confidence-ordered because within one class that is the
# order a reviewer wants. The taker joins are undirected and `:MANDATES`-scoped
# to the request's other edition, because one obligation serves every diff its
# edition is in — a middle edition belongs to two pairs, and direction alone
# cannot separate two diffs run from the same older edition. The greedy loop is
# one-to-one within an edition pair, so each side has at most one taker.
# Substituted rather than formatted: the query contains Cypher braces.
_CANDIDATES_TEMPLATE = """
MATCH (from_version:DocumentVersion {version_id: $from_version_id})
MATCH (to_version:DocumentVersion {version_id: $to_version_id})
MATCH (from_version)-[:MANDATES]->(old:Obligation)
      -[r:PAIRING_CANDIDATE]->
      (new:Obligation)<-[:MANDATES]-(to_version)
WHERE $outcome IS NULL OR r.outcome = $outcome
--OLD-ANCHOR--
--NEW-ANCHOR--
MATCH (old_doc:Document)-[:HAS_VERSION]->(from_version)
MATCH (new_doc:Document)-[:HAS_VERSION]->(to_version)
OPTIONAL MATCH (old)-[:PAIRING_CANDIDATE {outcome: 'auto_paired'}]-(old_taker:Obligation)
WHERE old_taker <> new
  AND EXISTS { MATCH (to_version)-[:MANDATES]->(old_taker) }
OPTIONAL MATCH (new)-[:PAIRING_CANDIDATE {outcome: 'auto_paired'}]-(new_taker:Obligation)
WHERE new_taker <> old
  AND EXISTS { MATCH (from_version)-[:MANDATES]->(new_taker) }
RETURN old.obligation_id       AS old_id,
       old.statement           AS old_statement,
       old.modality            AS old_modality,
       old_doc.name            AS old_document,
       from_version.version_id AS old_version_id,
       old_chunk.section_path  AS old_section_path,
       old_chunk.page          AS old_page,
       new.obligation_id       AS new_id,
       new.statement           AS new_statement,
       new.modality            AS new_modality,
       new_doc.name            AS new_document,
       to_version.version_id   AS new_version_id,
       new_chunk.section_path  AS new_section_path,
       new_chunk.page          AS new_page,
       r.confidence            AS confidence,
       r.rationale             AS rationale,
       r.outcome               AS outcome,
       old_taker.obligation_id AS old_taken_by,
       new_taker.obligation_id AS new_taken_by
ORDER BY r.confidence DESC, old_id, new_id
LIMIT $limit
"""

CANDIDATES = (
    _CANDIDATES_TEMPLATE
    .replace("--OLD-ANCHOR--", primary_anchor("old", "old_chunk"))
    .replace("--NEW-ANCHOR--", primary_anchor("new", "new_chunk"))
)

# Citations for the pairs `read_settled` returned. A separate query rather than
# a widening of `read_settled`, so which decisions belong to an edition pair
# stays decided in exactly one place (`links/pairing.py`'s `_SCOPE`) and this
# only dresses the answer. Each side resolves its own document and edition
# rather than binding the request's from/to: the decision's orientation is
# canonical older→newer, which the request's is too, but a citation that
# re-derived the edition from the request would print the wrong one the moment
# those two ever disagreed.
#
# Both obligations are guaranteed present — `_SCOPE` matches through `:MANDATES`
# on both, so a stranded decision is already absent from `settled` — and every
# obligation `write_obligations` writes is `ANCHORED_IN` a chunk, which is what
# lets the anchor be a plain (non-optional) join here.
_SETTLED_TEMPLATE = """
UNWIND $pairs AS pair
MATCH (old:Obligation {obligation_id: pair.old_id})
MATCH (new:Obligation {obligation_id: pair.new_id})
--OLD-ANCHOR--
--NEW-ANCHOR--
MATCH (old_doc:Document)-[:HAS_VERSION]->(old_version:DocumentVersion)
      -[:MANDATES]->(old)
MATCH (new_doc:Document)-[:HAS_VERSION]->(new_version:DocumentVersion)
      -[:MANDATES]->(new)
RETURN pair.old_id            AS old_id,
       old.statement          AS old_statement,
       old.modality           AS old_modality,
       old_doc.name           AS old_document,
       old_version.version_id AS old_version_id,
       old_chunk.section_path AS old_section_path,
       old_chunk.page         AS old_page,
       pair.new_id            AS new_id,
       new.statement          AS new_statement,
       new.modality           AS new_modality,
       new_doc.name           AS new_document,
       new_version.version_id AS new_version_id,
       new_chunk.section_path AS new_section_path,
       new_chunk.page         AS new_page
"""

SETTLED_CITATIONS = (
    _SETTLED_TEMPLATE
    .replace("--OLD-ANCHOR--", primary_anchor("old", "old_chunk"))
    .replace("--NEW-ANCHOR--", primary_anchor("new", "new_chunk"))
)

# The page's own match, counted without the LIMIT and without the outcome
# filter — the review queue's PENDING reason: the page is capped, and the number
# a reviewer needs is the backlog. No anti-join here, unlike review's, because
# none is needed: the diff never re-records a settled pair as a candidate — the
# `:PairingDecision` is the record — so every candidate edge between these two
# editions is an open question by construction.
#
# Grouped by outcome, and that is what makes the filter usable rather than a
# guessing game: the counts are the whole backlog's, so a reviewer looking at a
# page of `auto_paired` rows can see that four declines exist and ask for them.
# A single total cannot say that, and a count taken under the filter would
# vanish the moment it was applied.
PENDING_BY_OUTCOME = """
MATCH (:DocumentVersion {version_id: $from_version_id})-[:MANDATES]->(:Obligation)
      -[r:PAIRING_CANDIDATE]->
      (:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $to_version_id})
RETURN r.outcome AS outcome, count(r) AS total
"""

# Which document and edition hold an obligation, plus the edition's ordering
# tuple. An obligation belongs to exactly one edition — its id hashes the
# version_id (extraction/schema.py) — which is what lets the POST order the
# pair from nothing but the two path parameters.
RESOLVE_EDITION = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)
      -[:MANDATES]->(:Obligation {obligation_id: $obligation_id})
RETURN d.slug                                   AS document_slug,
       v.version_id                             AS version_id,
       coalesce(toString(v.effective_date), '') AS effective_date,
       coalesce(toString(v.ingested_at), '')    AS ingested_at
"""

# A live paired verdict naming $obligation_id with a *different* partner whose
# other end is `:MANDATES`-ed by the same other edition. Both roles are
# checked, because canonical direction puts a middle edition's clause on the
# old side of one decision and the new side of another. The `:MANDATES` scope
# is the whole point: an unscoped match would refuse B→C because A→B exists,
# and prescribe destroying a verdict from a different diff.
CONFLICTING = """
MATCH (d:PairingDecision {verdict: 'paired'})
WHERE (d.old_obligation_id = $obligation_id
       AND d.new_obligation_id <> $partner_id
       AND EXISTS {
           MATCH (:DocumentVersion {version_id: $other_version_id})
                 -[:MANDATES]->(:Obligation {obligation_id: d.new_obligation_id})
       })
   OR (d.new_obligation_id = $obligation_id
       AND d.old_obligation_id <> $partner_id
       AND EXISTS {
           MATCH (:DocumentVersion {version_id: $other_version_id})
                 -[:MANDATES]->(:Obligation {obligation_id: d.old_obligation_id})
       })
RETURN d.old_obligation_id AS old_id, d.new_obligation_id AS new_id
LIMIT 1
"""


def _citation(record, side: str) -> ObligationCitationOut:
    """One side of a pair, out of a record whose columns carry an `old_`/`new_`
    prefix.

    Shared by the candidate rows and the settled rows: both queries return the
    same seven columns per side under the same two prefixes, and a citation
    assembled twice is a citation that can come to disagree with itself.
    """
    return ObligationCitationOut(
        obligation_id=record[f"{side}_id"],
        statement=record[f"{side}_statement"],
        modality=record[f"{side}_modality"],
        document=record[f"{side}_document"],
        version_id=record[f"{side}_version_id"],
        section_path=record[f"{side}_section_path"],
        page=record[f"{side}_page"],
    )


def _require_version(driver: Driver, database: str, version_id: str) -> None:
    records, _, _ = driver.execute_query(
        VERSION_EXISTS,
        {"version_id": version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if records[0]["total"] == 0:
        raise HTTPException(
            status_code=404, detail=f"No edition with version_id {version_id!r}."
        )


@router.get("/queue", response_model=PairingQueueOut)
def queue(
    from_version_id: str = Query(...),
    to_version_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    outcome: str | None = Query(default=None),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> PairingQueueOut:
    """What the diff decided between two editions, and what a person settled.

    An unknown edition is a 404 for Triage's reason: an empty queue reads as
    "nothing to settle", which a mistyped version id must not be able to say.
    A pair that is not older→newer by the corpus ordering is a 400, because
    everything below this point binds request order and calls it from/to.

    `outcome` narrows the page to one of the diff's labels, and the screen needs
    it: the page is capped and a decline always scores at or below the pair that
    beat it, so an unfiltered page of a heavily reworded edition pair holds only
    pairings the diff already made. `pending_by_outcome` counts the whole
    backlog by label, unfiltered, so the filter can be offered with the number
    behind it rather than as a question.
    """
    database = settings.neo4j_database
    if outcome is not None and outcome not in OUTCOMES:
        # Refused rather than answered with an empty page, for the 404's reason:
        # a mistyped label would read as "no candidate of that kind is waiting",
        # which is the one thing a queue must not say by accident.
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown outcome {outcome!r}; the diff labels a candidate with "
                f"one of {list(OUTCOMES)}."
            ),
        )
    _require_version(driver, database, from_version_id)
    _require_version(driver, database, to_version_id)

    records, _, _ = driver.execute_query(
        ORDERING,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    ordering = {
        record["version_id"]: (
            record["effective_date"],
            record["ingested_at"],
            record["version_id"],
        )
        for record in records
    }
    documents = {
        record["version_id"]: record["document_slug"] for record in records
    }
    # Refused before the diff runs, and that ordering is the point: the diff
    # writes `:Change` nodes and `PAIRING_CANDIDATE` edges, so a cross-document
    # request answered late leaves behind a derived assertion that one
    # instrument's clause is the reworded form of another's — written as the
    # side effect of a GET, which no POST would ever accept.
    #
    # This is the same argument that put the guard in `record_pairing` rather
    # than in the POST alone: a rule enforced at one caller is a rule only that
    # caller obeys, and without this the queue offered rows its own POST
    # answers 404. Triage's willingness to diff any two editions is not cover —
    # Triage has no settle action, so it cannot offer a row that cannot be
    # settled.
    if documents[from_version_id] != documents[to_version_id]:
        raise HTTPException(
            status_code=404,
            detail=(
                "A pairing runs between two editions of one document; "
                f"{from_version_id!r} belongs to "
                f"{documents[from_version_id]!r} and {to_version_id!r} to "
                f"{documents[to_version_id]!r}. Whether one document's clause "
                "discharges another's is Review's question, not this one."
            ),
        )
    if not ordering[from_version_id] < ordering[to_version_id]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{from_version_id!r} does not precede {to_version_id!r} by the "
                "corpus ordering (effective date, then ingest time, then version "
                "id). The queue's question is one-directional — is the newer "
                "clause the older one reworded? — so a reversed pair would be "
                "answered upside down and its candidate edges written backwards. "
                "Put the older edition first: that is from_version_id, and on "
                "the Pairings screen it is the picker labelled 'Older edition'."
            ),
        )

    def _work(tx):
        counts = diff_versions(
            tx, from_version_id=from_version_id, to_version_id=to_version_id
        )
        candidates = [
            dict(record)
            for record in tx.run(
                CANDIDATES,
                {
                    "from_version_id": from_version_id,
                    "to_version_id": to_version_id,
                    "limit": limit,
                    "outcome": outcome,
                },
            )
        ]
        settled = read_settled(
            tx, from_version_id=from_version_id, to_version_id=to_version_id
        )
        citations = {}
        if settled:
            citations = {
                (record["old_id"], record["new_id"]): dict(record)
                for record in tx.run(
                    SETTLED_CITATIONS,
                    {
                        "pairs": [
                            {"old_id": entry["old_id"], "new_id": entry["new_id"]}
                            for entry in settled
                        ]
                    },
                )
            }
        pending_by_outcome = {
            record["outcome"]: record["total"]
            for record in tx.run(
                PENDING_BY_OUTCOME,
                {
                    "from_version_id": from_version_id,
                    "to_version_id": to_version_id,
                },
            )
        }
        return counts, candidates, settled, citations, pending_by_outcome

    with driver.session(database=database) as session:
        counts, candidates, settled, citations, pending_by_outcome = (
            session.execute_write(_work)
        )

    return PairingQueueOut(
        items=[
            PairingCandidateOut(
                old=_citation(record, "old"),
                new=_citation(record, "new"),
                confidence=record["confidence"],
                rationale=record["rationale"],
                outcome=record["outcome"],
                taken_by=[
                    taker
                    for taker in (record["old_taken_by"], record["new_taken_by"])
                    if taker is not None
                ],
            )
            for record in candidates
        ],
        settled=[
            PairingSettledOut(
                # Indexed, not `.get`-ed. `read_settled` decides which
                # decisions belong to this edition pair and its scope matches
                # both obligations through `:MANDATES`, so a pair it returned
                # and this could not cite is a graph state neither query
                # models. Failing loudly beats dropping the row: this list is
                # the only route back to a recorded verdict, and a settled pair
                # quietly missing from it is a verdict a reviewer can no longer
                # undo.
                old=_citation(citations[(entry["old_id"], entry["new_id"])], "old"),
                new=_citation(citations[(entry["old_id"], entry["new_id"])], "new"),
                verdict=entry["verdict"],
                actor=entry["actor"],
                rationale=entry["rationale"],
            )
            for entry in settled
        ],
        pairings_unapplied=counts["pairings_unapplied"],
        pending=sum(pending_by_outcome.values()),
        pending_by_outcome=pending_by_outcome,
    )


@router.post(
    "/{old_obligation_id}/{new_obligation_id}", response_model=PairingVerdictOut
)
def settle(
    old_obligation_id: str,
    new_obligation_id: str,
    body: PairingVerdictIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> PairingVerdictOut:
    """Record a pairing verdict. `actor` is `principal.name`; the body has no
    say in it.

    The route orders the pair older→newer itself before keying, whatever order
    the path gave it — the obligation ids determine the editions, the editions
    order by the corpus rule. The key is a directional hash, so a mis-oriented
    record could never be replaced by a later verdict on the same pair, only
    MERGE-d beside it.

    One conflict is refused rather than recorded, inside the same transaction
    that would record it: a paired verdict naming a clause that already carries
    a live paired verdict with a different partner *in the same other edition*
    is a 409 naming the pairing to mark distinct first. The scope matters — a
    middle edition's clause legitimately pairs into both adjacent pairs.
    """
    database = settings.neo4j_database
    if body.verdict not in set(PairingVerdict):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown verdict {body.verdict!r}; expected one of "
                f"{[v.value for v in PairingVerdict]}."
            ),
        )

    editions = {}
    for obligation_id in (old_obligation_id, new_obligation_id):
        records, _, _ = driver.execute_query(
            RESOLVE_EDITION,
            {"obligation_id": obligation_id},
            database_=database,
            routing_=RoutingControl.READ,
        )
        if not records:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No obligation {obligation_id!r} held by any edition. A "
                    "pairing verdict is recorded against two clauses that exist."
                ),
            )
        editions[obligation_id] = records[0]

    first = editions[old_obligation_id]
    second = editions[new_obligation_id]
    if first["document_slug"] != second["document_slug"]:
        raise HTTPException(
            status_code=404,
            detail=(
                "A pairing runs between two editions of one document; these "
                f"obligations belong to {first['document_slug']!r} and "
                f"{second['document_slug']!r}. Whether one document's clause "
                "discharges another's is Review's question, not this one."
            ),
        )
    if first["version_id"] == second["version_id"]:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Both obligations belong to edition {first['version_id']!r}; "
                "a pairing runs between two editions of one document."
            ),
        )

    def _key(row) -> tuple[str, str, str]:
        return (row["effective_date"], row["ingested_at"], row["version_id"])

    old_id, new_id = old_obligation_id, new_obligation_id
    if _key(second) < _key(first):
        old_id, new_id = new_obligation_id, old_obligation_id
    old_edition = editions[old_id]["version_id"]
    new_edition = editions[new_id]["version_id"]

    def _write(tx):
        # The lock comes first, and it is what gives the conflict check below
        # any force at all. Neo4j is read-committed and locks nothing for
        # reads, and two verdicts on one clause MERGE two *different*
        # `:PairingDecision` nodes — so merely putting the read in the same
        # transaction as the write serialises nothing, and two concurrent
        # verdicts both read an empty conflict and both commit. Taking the
        # edition pair's lock before reading makes the second transaction block
        # until the first commits, so it reads the first's decision and 409s.
        # See `links.pairing.ACQUIRE_PAIR_LOCK` for why the scope is the
        # edition pair and why the constraint in db.py is part of the
        # mechanism.
        lock_edition_pair(
            tx, old_version_id=old_edition, new_version_id=new_edition
        )
        if body.verdict == PairingVerdict.PAIRED:
            for obligation_id, partner_id, other_version_id in (
                (old_id, new_id, new_edition),
                (new_id, old_id, old_edition),
            ):
                conflict = tx.run(
                    CONFLICTING,
                    {
                        "obligation_id": obligation_id,
                        "partner_id": partner_id,
                        "other_version_id": other_version_id,
                    },
                ).single()
                if conflict is not None:
                    return dict(conflict)
        record_pairing(
            tx,
            old_id=old_id,
            new_id=new_id,
            verdict=body.verdict,
            actor=principal.name,
            rationale=body.rationale,
        )
        return None

    try:
        with driver.session(database=database) as session:
            conflict = session.execute_write(_write)
    except CrossDocumentPair as exc:
        # `record_pairing`'s own refusal. The slug comparison above screens the
        # same pair first and answers 404, so this arm is reached only when the
        # two disagree — the resolve picks one document per obligation and the
        # recorder looks at every one, so a graph where an edition hangs off two
        # documents separates them. Caught by type, not as `ValueError`: the
        # driver raises a bare one out of `execute_write` when a parameter
        # cannot be packed, and answering that with this wording would tell a
        # reviewer something false about their data. A fault we cannot explain
        # must stay a 500.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if conflict is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A live paired verdict already links {conflict['old_id']} → "
                f"{conflict['new_id']} within this edition pair, and the diff "
                "is one-to-one: two live paired verdicts on one clause would "
                "leave the loser chosen by iteration order. Mark that pairing "
                "distinct first, then re-record this one."
            ),
        )

    return PairingVerdictOut(
        old_id=old_id, new_id=new_id, verdict=body.verdict, actor=principal.name
    )
