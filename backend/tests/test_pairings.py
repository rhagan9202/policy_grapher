"""The pairing queue and the verdicts that settle it.

Everything here goes through the API, because the API is the claim under test:
the queue runs the diff itself — `diff_versions`' only other caller is the
Triage GET, so a queue that merely read candidate edges would be empty for any
edition pair nobody had opened in Triage — and the POST needs no recorded
candidate edge, because gating on one would make the recorder outrank the
person for exactly the declines the design exists to reach.

The seeded editions carry no `effective_date` and no `ingested_at`, on
purpose: the corpus ordering rule then falls all the way through to the
`version_id` tie-breaker this feature adds, so these tests exercise it rather
than passing over it.
"""

import re
import threading
from collections import Counter

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    WORD_MODALITIES,
    ExtractedObligation,
    Modality,
)
from policy_grapher.links.pairing import pairing_key
from policy_grapher.models import (
    PairingCandidateOut,
    PairingQueueOut,
    PairingSettledOut,
    PairingVerdictOut,
)
from policy_grapher.obligations import write_obligations
from policy_grapher.routers import pairings

# The pair test_diff.py proves the wording pass auto-pairs: distinctive shared
# vocabulary well over PAIRING_CONFIDENCE, seeded across two different sections
# so the section rule cannot reach it first and pass 3 must.
REWORDED_OLD = (
    "All of the DoD Components shall acquire systems, subsystems, equipment, "
    "supplies, and services in accordance with the statutory requirements for "
    "competition."
)
REWORDED_NEW = (
    "The DoD Components will acquire systems, subsystems, equipment, supplies, "
    "product support, sustainment, and services in accordance with the "
    "statutory requirements for competition."
)

# No content words at all — every word is a stopword or under three letters —
# so `score_pair` returns None before scoring (propose.py:61-62). This is the
# silent exclusion class from the problem section, and the case a human most
# obviously beats the measure: a complete rewording sharing no content words.
BLANK_OLD = "They shall not do so."
BLANK_NEW = "It must all be this."
RIVAL = "They must not do it."
# A second *old*-side clause with no content words either. The conflict rule
# checks both roles, and the rival-on-the-old-side case needs a clause the
# scorer will not pair with anything by accident.
RIVAL_OLD = "They shall not have this."

# The taker fixtures, scored by the real measure rather than a stub, because the
# join under test is Cypher and only the API reaches it. Under
# `links/propose.py`'s scorer these give test_diff.py's both-sides-taken shape at
# the confidences this corpus's own measure produces:
#   STRATEGY_OLD ~ STRATEGY_NEW  1.00 (identical content words)
#   FUNDS_OLD    ~ MERGED_NEW    0.91 (ten of eleven)
#   STRATEGY_OLD ~ MERGED_NEW    0.80 (eight of ten) — declined, both ends taken
#   FUNDS_OLD    ~ STRATEGY_NEW  unscored (no shared content word at all)
#   MERGED_NEW   ~ FUNDS_LATER   0.91 — a second edition pair's winner
# MERGED_NEW is deliberately the merge of the other two: it is the clause that
# belongs to two diffs at once, which is the whole difficulty `taken_by` has.
STRATEGY_OLD = (
    "Program managers shall prepare a cybersecurity strategy for the milestone "
    "decision on each acquisition category systems program."
)
STRATEGY_NEW = (
    "For each acquisition category systems program, the program managers will "
    "prepare a cybersecurity strategy before the milestone decision."
)
FUNDS_OLD = (
    "Contracting officers shall obligate funds by competitive procurement of "
    "sustainment services above the dollar thresholds."
)
MERGED_NEW = (
    "Contracting officers and program managers will obligate funds by "
    "competitive procurement of sustainment support above the dollar "
    "thresholds, and will prepare a cybersecurity strategy for the acquisition "
    "category systems program."
)
FUNDS_LATER = (
    "Contracting officers must obligate funds by competitive procurement of "
    "sustainment above the dollar thresholds annually."
)


def _modality_of(statement: str) -> Modality:
    """The modality whose word this statement actually uses.

    `ExtractedObligation` refuses a modality the statement does not contain
    (extraction/schema.py), and these fixtures vary the modal verb between
    editions on purpose: `shall` re-issued as `will` is the corpus's own
    generational rewrite and part of what makes the newer clause a rewording of
    the older. A fixed modality would make half of them unconstructible.
    """
    found = [
        modality
        for modality in sorted(WORD_MODALITIES)
        if re.search(rf"\b{modality.value}\b", statement, re.IGNORECASE)
    ]
    assert len(found) == 1, (statement, found)
    return found[0]


def _seed(driver, database, *, doc_slug, version_id, entries, effective_date=None):
    """`entries` is (section, statement) pairs; returns {statement: obligation_id}.

    Editions are created bare by default — no effective_date, no ingested_at —
    so ordering rests on the version_id tie-breaker; choose ids that sort
    chronologically.

    `effective_date`, when given, is written as a Neo4j `date` — a real
    temporal type rather than the ISO string the ingest path stores. That is
    deliberately the awkward case: it is the only one that can tell the route's
    `toString` apart from an unwrapped read of the same property.
    """
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"slug": doc_slug, "vid": version_id},
        database_=database,
    )
    if effective_date is not None:
        driver.execute_query(
            "MATCH (v:DocumentVersion {version_id: $vid}) "
            "SET v.effective_date = date($effective)",
            {"vid": version_id, "effective": effective_date},
            database_=database,
        )
    ids = {}
    with driver.session(database=database) as session:
        for section, statement in entries:
            chunk = chunk_pages(
                [f"{section}. TITLE.\nBody text.\n"], version_id=version_id
            )[-1]
            session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=_modality_of(statement),
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                ],
            )
            records, _, _ = driver.execute_query(
                "MATCH (:DocumentVersion {version_id: $vid})-[:MANDATES]->"
                "(o:Obligation {statement: $statement}) "
                "RETURN o.obligation_id AS id",
                {"vid": version_id, "statement": statement},
                database_=database,
            )
            ids[statement] = records[0]["id"]
    return ids


@pytest.mark.integration
def test_the_queue_returns_candidates_for_a_pair_never_opened_in_triage(
    client_with_auth,
):
    """The route runs the diff itself. Candidate edges are written from inside
    `diff_versions`, whose only other caller is the Triage GET — a queue that
    merely read them would be empty until someone happened to load that screen,
    and a verdict would take effect only the next time they did."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    )
    assert response.status_code == 200

    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["old"]["obligation_id"] == old_ids[REWORDED_OLD]
    assert item["new"]["obligation_id"] == new_ids[REWORDED_NEW]
    assert item["old"]["version_id"] == "pol@2018"
    assert item["new"]["version_id"] == "pol@2020"
    assert item["old"]["section_path"] == ["3.2"]
    assert item["new"]["section_path"] == ["4.1"]
    assert item["outcome"] == "auto_paired"
    assert item["confidence"] >= 0.75
    assert item["taken_by"] == []
    assert body["settled"] == []
    assert body["pending"] == 1
    assert body["pairings_unapplied"] == 0


@pytest.mark.integration
def test_a_taker_from_a_third_edition_does_not_appear_in_taken_by(client_with_auth):
    """`taken_by` names the winners of *this* diff, and only the `:MANDATES`
    scope can say which those are.

    One obligation serves every diff its edition is in, so `MERGED_NEW` ends up
    carrying two `auto_paired` edges: one to `FUNDS_OLD` in `pol@2018`, one to
    `FUNDS_LATER` in `pol@2022`. Only the first answers the question the screen
    is asking — what consumed this end of the pair in front of you — and
    direction cannot separate them, because `MERGED_NEW` is the new side of one
    edge and the old side of the other. Hence the undirected taker joins scoped
    to the request's own editions.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", STRATEGY_OLD), ("3.3", FUNDS_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", STRATEGY_NEW), ("4.2", MERGED_NEW)],
    )
    later_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2022",
        entries=[("5.1", FUNDS_LATER)],
    )

    # The later pair is diffed first, so its winner's edge is in the graph with
    # every opportunity to leak into the earlier pair's answer. It survives that
    # second run: `drop_candidates` clears only the edges between the two
    # editions it is given.
    later = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2020", "to_version_id": "pol@2022"},
    )
    assert later.status_code == 200
    assert [item["outcome"] for item in later.json()["items"]] == ["auto_paired"]

    body = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    ).json()

    declined = [
        item
        for item in body["items"]
        if item["old"]["obligation_id"] == old_ids[STRATEGY_OLD]
        and item["new"]["obligation_id"] == new_ids[MERGED_NEW]
    ]
    assert len(declined) == 1
    assert declined[0]["outcome"] == "partner_taken"
    # Old side's taker first, new side's second — the order the route builds the
    # list in. `STRATEGY_NEW` took the old end, `FUNDS_OLD` took the new one.
    assert declined[0]["taken_by"] == [
        new_ids[STRATEGY_NEW],
        old_ids[FUNDS_OLD],
    ]
    assert later_ids[FUNDS_LATER] not in declined[0]["taken_by"]


# A clause with enough distinctive vocabulary of its own that the wording pass
# scores it against nothing else, paired with a rewrite sharing only the two
# words that name the actor: 0.40, which is over `MIN_CONFIDENCE` and under
# `PAIRING_CONFIDENCE`. A decline the bound keeps, because both ends finish the
# greedy loop unpaired and it is the only sub-threshold candidate either has.
DECLINED_OLD = (
    "Installation commanders shall inspect barracks plumbing, wiring, heating "
    "and drainage twice each winter."
)
DECLINED_NEW = "Installation commanders will publish roofing standards."


@pytest.mark.integration
def test_a_decline_is_reachable_behind_a_page_full_of_pairings_the_diff_made(
    client_with_auth,
):
    """The queue exists to settle what the diff declined, and without the
    outcome filter it cannot reach one.

    Every candidate at or above `PAIRING_CONFIDENCE` is recorded
    unconditionally, and a decline is by construction at or below the confidence
    of whatever beat it — `partner_taken` never outscores the winner that
    consumed its endpoint, `contested` sits within `PAIRING_MARGIN` of its
    rival, `below_threshold` is under the bar entirely. `CANDIDATES` orders by
    `confidence DESC` and caps the page, so the declines are what the cap cuts,
    at every value of the cap. Measured live on a 61-clause edition pair: the
    default page returned 50 rows, every one `auto_paired`, and the single
    decline appeared only at `limit=500`.

    The cap is `limit=3` here rather than the default 50 because the burial does
    not depend on its value: three pairings the diff made fill a three-row page
    exactly as sixty fill fifty, and a fixture of sixty mutually
    non-contesting pairs would measure the scorer rather than this route. What
    the test pins is that the filter reaches the class the page cannot hold, and
    that the breakdown says the class is there to ask for.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[
            ("3.1", REWORDED_OLD),
            ("3.2", STRATEGY_OLD),
            ("3.3", FUNDS_OLD),
            ("3.4", DECLINED_OLD),
        ],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[
            ("4.1", REWORDED_NEW),
            ("4.2", STRATEGY_NEW),
            ("4.3", FUNDS_LATER),
            ("4.4", DECLINED_NEW),
        ],
    )

    page = client_with_auth.get(
        "/pairings/queue",
        params={
            "from_version_id": "pol@2018",
            "to_version_id": "pol@2020",
            "limit": 3,
        },
    )
    assert page.status_code == 200
    body = page.json()
    # The page the reviewer is given: three pairings the diff already made, and
    # no sign of the one pair it could not.
    assert [item["outcome"] for item in body["items"]] == ["auto_paired"] * 3
    assert body["pending"] == 4
    # The breakdown counts the backlog, not the page — which is the only reason
    # a reviewer knows to ask for the decline at all.
    assert body["pending_by_outcome"] == {"auto_paired": 3, "below_threshold": 1}

    declines = client_with_auth.get(
        "/pairings/queue",
        params={
            "from_version_id": "pol@2018",
            "to_version_id": "pol@2020",
            "limit": 3,
            "outcome": "below_threshold",
        },
    )
    assert declines.status_code == 200
    settled_page = declines.json()
    assert [item["outcome"] for item in settled_page["items"]] == ["below_threshold"]
    reached = settled_page["items"][0]
    assert reached["old"]["obligation_id"] == old_ids[DECLINED_OLD]
    assert reached["new"]["obligation_id"] == new_ids[DECLINED_NEW]
    # The filter narrows the page and nothing else: the backlog and its
    # breakdown are the same numbers as the unfiltered request returned, so the
    # count that justifies the filter does not vanish once it is applied.
    assert settled_page["pending"] == 4
    assert settled_page["pending_by_outcome"] == {
        "auto_paired": 3,
        "below_threshold": 1,
    }


@pytest.mark.integration
def test_an_unknown_outcome_filter_is_refused_rather_than_answered_empty(
    client_with_auth,
):
    """A mistyped filter must not read as "nothing of that kind is waiting".

    Same argument as the 404 for an unknown edition: an empty queue is an
    answer, and a typo must not be able to give it. The labels come from
    `changes.diff.OUTCOMES`, so the route cannot drift from the writer.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={
            "from_version_id": "pol@2018",
            "to_version_id": "pol@2020",
            "outcome": "declined",
        },
    )

    assert response.status_code == 400
    assert "below_threshold" in response.json()["detail"]


@pytest.mark.integration
def test_a_reversed_pair_is_a_400_not_a_reversed_diff(client_with_auth):
    """Nothing beneath this route carries chronology — `diff_versions` binds
    whatever from/to it is given — so a reversed pair would quietly write
    reversed candidate edges and serve a reviewer a queue whose question is
    upside down. These editions are undated and carry no ingested_at, so the
    refusal here is the version_id tie-breaker doing its work."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2020", "to_version_id": "pol@2018"},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "older" in detail
    # The remedy, not merely the diagnosis. "older" appears in this route's own
    # statement of the question it asks, so the word alone is satisfied by a
    # message that never says which of the two parameters is in the wrong
    # place — and the two version ids are both in the message either way. The
    # caller needs the one naming the end to move.
    assert "from_version_id" in detail


@pytest.mark.integration
def test_a_temporally_typed_effective_date_orders_the_pair_and_beats_version_id(
    client_with_auth,
):
    """Both writers must read the ordering's first leg the same way, and only a
    real temporal type can show they do.

    `migrate.py` reads all three legs through `toString`; so does this route.
    They agree today whatever either does, because `versions.merge_version`
    stores `effective_date` as an ISO string — which is exactly why an
    unwrapped read here is invisible in every other test in this file.

    **One edition dated and one not, which is what makes the types differ.**
    Two `date`-typed editions compare perfectly well unwrapped, because
    `Date < Date` is defined — the first version of this test made that mistake
    and passed against the unwrapped read. It is the *mixed* pair that bites:
    an absent date coalesces to `''`, so an unwrapped read compares a
    `neo4j.time.Date` against a `str` and raises `TypeError: '<' not supported
    between instances of 'Date' and 'str'` — a 500 on the GET, and a 500 on the
    POST before any verdict is recorded.

    That an undated edition sorts *before* a dated one is a consequence of
    coalescing to `''`, not a preference anyone chose; what this pins is that
    both writers reach the same consequence. The version ids sort against that
    answer on purpose — `pol@aaa-2020` precedes `pol@zzz-nodate`
    lexically — so a route that fell through to the tie-breaker, or failed to
    compare the first leg at all, gets the pair backwards rather than right by
    luck.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    older = _seed(
        driver, database, doc_slug="pol", version_id="pol@zzz-nodate",
        entries=[("3.2", BLANK_OLD)],
    )
    newer = _seed(
        driver, database, doc_slug="pol", version_id="pol@aaa-2020",
        entries=[("4.1", BLANK_NEW)], effective_date="2020-07-28",
    )

    forward = client_with_auth.get(
        "/pairings/queue",
        params={
            "from_version_id": "pol@zzz-nodate",
            "to_version_id": "pol@aaa-2020",
        },
    )
    assert forward.status_code == 200, forward.text

    backward = client_with_auth.get(
        "/pairings/queue",
        params={
            "from_version_id": "pol@aaa-2020",
            "to_version_id": "pol@zzz-nodate",
        },
    )
    assert backward.status_code == 400, backward.text

    # Posted newer-first, so the swap has to read the dates to get this right.
    recorded = client_with_auth.post(
        f"/pairings/{newer[BLANK_NEW]}/{older[BLANK_OLD]}",
        json={"verdict": "paired"},
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["old_id"] == older[BLANK_OLD]
    assert recorded.json()["new_id"] == newer[BLANK_NEW]

    # The key the migration would compute for the same pair. This is the whole
    # stake: `pairing_key` is directional, so two writers that ordered this
    # pair differently would key a re-verdict to a second decision beside the
    # first instead of replacing it.
    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision) RETURN d.key AS key", database_=database
    )
    assert [record["key"] for record in records] == [
        pairing_key(older[BLANK_OLD], newer[BLANK_NEW])
    ]


@pytest.mark.integration
def test_a_verdict_needs_no_recorded_candidate(client_with_auth):
    """Admissibility is membership, not a recorded edge. These two statements
    have no content words, so `score_pair` never scores them at all — no
    candidate edge exists or ever will — and this pair is exactly the one a
    human most obviously beats the measure on."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired", "rationale": "a complete rewording"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_id"] == old_ids[BLANK_OLD]
    assert body["new_id"] == new_ids[BLANK_NEW]
    assert body["verdict"] == "paired"
    assert body["actor"] == "tester"


@pytest.mark.integration
def test_a_cross_document_pair_is_a_404(client_with_auth):
    """The pairing question is same-document by definition — is the newer
    clause the older one reworded? Two documents ask the other question, under
    the other vocabulary, on the Review screen."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    a_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    b_ids = _seed(
        driver, database, doc_slug="other", version_id="other@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{a_ids[BLANK_OLD]}/{b_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    # *Which* refusal fired, not merely that one did. Two guards now refuse
    # this pair and they answer differently: `record_pairing`'s own guard
    # raises `CrossDocumentPair`, which the route maps to 400 and which says
    # "implements question"; this route's membership screen answers 404 and
    # sends the reviewer to Review. The status code alone cannot tell them
    # apart — deleting this screen still refuses the pair, just with the other
    # code and the other next step — and the two prescribe different actions.
    #
    # Both slugs quoted, for the reason its sibling in `test_pairing.py`
    # argues at length: unquoted, "pol" and "other" are satisfied by the
    # refusal's own prose, and the ids in the message are content hashes, so
    # naming the two instruments is what makes it actionable.
    assert "'pol'" in detail
    assert "'other'" in detail
    assert "Review" in detail

    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0, "a refused verdict must leave no audit record"


@pytest.mark.integration
def test_the_queue_refuses_a_cross_document_pair_before_the_diff_writes(
    client_with_auth,
):
    """The GET owes the same rule as the POST, and owes it *before* the diff.

    Without this the queue served rows its own POST answers 404 — and served
    them by writing them: `diff_versions` records a `:Change` and a
    `PAIRING_CANDIDATE` edge, so a cross-document request left behind a derived
    assertion that one instrument's clause is the reworded form of another's,
    as the side effect of a GET. This is criterion 3's argument pointed at the
    other caller: a rule enforced at one caller is a rule only that caller
    obeys.

    The two statements auto-pair on wording, so the mutant that drops the check
    does not merely answer 200 — it writes the edge.

    **The pair is deliberately WELL-ORIENTED, and that is what makes the
    no-write assertions below capable of failing.** Both editions are bare, so
    ordering falls through to the version_id tie-breaker, and
    `'other@2018' < 'pol@2020'` — so the reversed-pair 400 does not fire and the
    document check is the only guard that can refuse this request. The first
    version of this test had it the other way round (`pol@2018` → `other@2020`,
    which the tie-breaker reads as reversed): with the document check deleted
    that request was refused by the 400 *before the diff ran*, so `changes == 0`
    and `edges == 0` held for a reason that had nothing to do with the finding,
    and moving the document check to after the write would have passed too.
    Measured on the mis-oriented fixture: guard deleted,
    `status=400 changes=0 edges=0`. On this one: `status=200 changes=1 edges=1`.

    `status_code == 404` is therefore also the assertion that the orientation is
    still right — a fixture that drifted back to reversed would answer 400 here.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed(
        driver, database, doc_slug="other", version_id="other@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "other@2018", "to_version_id": "pol@2020"},
    )

    assert response.status_code == 404, response.text
    detail = response.json()["detail"]
    assert "'pol'" in detail
    assert "'other'" in detail

    # Refused before the diff, not after it. A 404 that had already written the
    # derived record would leave the graph asserting the pairing it just
    # declined to offer.
    changes, _, _ = driver.execute_query(
        "MATCH (c:Change) RETURN count(c) AS total", database_=database
    )
    assert changes[0]["total"] == 0
    edges, _, _ = driver.execute_query(
        "MATCH ()-[r:PAIRING_CANDIDATE]->() RETURN count(r) AS total",
        database_=database,
    )
    assert edges[0]["total"] == 0


@pytest.mark.integration
def test_a_newer_first_post_is_recorded_older_to_newer(client_with_auth):
    """Direction is older→newer and only the route can enforce it — the
    obligation ids determine the editions, the editions order. `key` is a
    directional hash, so a mis-oriented record would never be replaced by a
    later verdict on the same pair, only MERGE-d beside it."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    response = client_with_auth.post(
        f"/pairings/{new_ids[BLANK_NEW]}/{old_ids[BLANK_OLD]}",
        json={"verdict": "paired"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["old_id"] == old_ids[BLANK_OLD]
    assert body["new_id"] == new_ids[BLANK_NEW]

    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision) "
        "RETURN d.old_obligation_id AS old_id, d.new_obligation_id AS new_id, "
        "d.key AS key",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old_id"] == old_ids[BLANK_OLD]
    assert records[0]["new_id"] == new_ids[BLANK_NEW]
    assert records[0]["key"] == pairing_key(
        old_ids[BLANK_OLD], new_ids[BLANK_NEW]
    )


@pytest.mark.integration
def test_a_second_paired_verdict_on_one_clause_in_one_pair_is_a_409(
    client_with_auth,
):
    """The diff is one-to-one within an edition pair, so two live paired
    verdicts on one clause is a state whose loser would be chosen by dict
    iteration order. Refused at the source, with the remedy named: the detail
    says which pairing to mark distinct first."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW), ("5.1", RIVAL)],
    )

    first = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    assert first.status_code == 200

    second = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[RIVAL]}",
        json={"verdict": "paired"},
    )

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "distinct" in detail
    assert new_ids[BLANK_NEW] in detail


@pytest.mark.integration
def test_a_second_paired_verdict_on_the_old_side_is_also_a_409(client_with_auth):
    """The other role, and it was unpinned: two *old* clauses both paired to one
    *new* clause.

    `CONFLICTING` checks both roles because canonical direction puts a middle
    edition's clause on the old side of one decision and the new side of
    another — so a conflict rule written for one role only looks complete and
    leaves half the shared-endpoint states reachable. Reducing the loop to its
    first leg left every other test in this file green.

    The state it admits is the same one `changes/diff.py` says it cannot
    arbitrate: one clause consumed twice, with the loser decided by dict
    iteration order and reported as a pass-1 pre-emption.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD), ("3.3", RIVAL_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )

    first = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    assert first.status_code == 200

    second = client_with_auth.post(
        f"/pairings/{old_ids[RIVAL_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )

    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "distinct" in detail
    # The pairing to undo is named by the clause that already holds the new
    # side — the old one, here, which is the half this role adds.
    assert old_ids[BLANK_OLD] in detail

    live, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision {verdict: 'paired'}) RETURN count(d) AS total",
        database_=database,
    )
    assert live[0]["total"] == 1


@pytest.mark.integration
def test_the_remedy_the_409_prescribes_can_actually_be_followed(client_with_auth):
    """The refusal names a next step; this walks it end to end.

    "Mark that pairing distinct first, then re-record this one" is only
    followable because `CONFLICTING` filters on `verdict: 'paired'`. Drop that
    filter and every test in this file still passes, while the remedy becomes
    impossible: the `distinct` verdict the reviewer is told to record stays a
    conflict, so the retry 409s for ever and the message sends them round a
    loop with no exit.

    The reversal is also the reason `distinct` must not be refused by the same
    rule — it is the only way out of a mis-pairing.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW), ("5.1", RIVAL)],
    )

    paired = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    assert paired.status_code == 200

    refused = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[RIVAL]}",
        json={"verdict": "paired"},
    )
    assert refused.status_code == 409
    # The remedy, read out of the refusal rather than assumed: the message
    # names the pairing to mark distinct, and that is the pair this follows.
    assert new_ids[BLANK_NEW] in refused.json()["detail"]

    undone = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "distinct", "rationale": "not the same duty after all"},
    )
    assert undone.status_code == 200

    retried = client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[RIVAL]}",
        json={"verdict": "paired"},
    )
    assert retried.status_code == 200, (
        "the 409's own prescribed remedy must leave the retry able to succeed"
    )

    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision) "
        "RETURN d.new_obligation_id AS new_id, d.verdict AS verdict "
        "ORDER BY d.verdict",
        database_=database,
    )
    assert [(r["new_id"], r["verdict"]) for r in records] == [
        (new_ids[BLANK_NEW], "distinct"),
        (new_ids[RIVAL], "paired"),
    ]


# Every barrier in the race harness below uses this, and both of them use it —
# symmetry is the point. A thread that dies before an untimed barrier hangs the
# run instead of failing it, and a hung suite reports nothing at all.
BARRIER_TIMEOUT = 2


def _race_two_paired_verdicts(
    client, monkeypatch, *, old_id, first_new_id, second_new_id
):
    """Post two `paired` verdicts naming `old_id` at once; return the statuses.

    **Two synchronisation points, and the second is what makes this a test
    rather than a coin toss.** Barriering only the two requests leaves the
    outcome to timing — measured against the unlocked route, that version
    passed one run in three, which is a false green on the one invariant the
    409 exists to hold. So the write is gated too: wrapping `record_pairing`
    where the route calls it puts the gate exactly between the conflict read
    and the write, which is the window under test.

    An unlocked route then has both reads complete before either write,
    deterministically, and both verdicts land. A locked one cannot reach that
    barrier twice — the second transaction is still blocked on the lock — so the
    first times out, commits, and the second then reads the committed decision
    and refuses. The timeout is the healthy path's cost and is paid on every
    green run.

    Statuses come back as a `Counter` rather than a sorted list because a
    thread that never started records a string, and `sorted` on mixed ints and
    strings raises `TypeError` — which would replace a readable failure with a
    confusing one.
    """
    start = threading.Barrier(2)
    before_write = threading.Barrier(2)
    real_record_pairing = pairings.record_pairing

    def gated_record_pairing(tx, **kwargs):
        try:
            before_write.wait(timeout=BARRIER_TIMEOUT)
        except threading.BrokenBarrierError:
            # The expected path when the lock works: the other transaction is
            # blocked on it and will never arrive. Proceed and commit, which is
            # what lets it read this decision.
            pass
        return real_record_pairing(tx, **kwargs)

    monkeypatch.setattr(pairings, "record_pairing", gated_record_pairing)

    outcomes = {}

    def settle(name, new_id):
        try:
            start.wait(timeout=BARRIER_TIMEOUT)
        except threading.BrokenBarrierError:
            outcomes[name] = "never started"
            return
        outcomes[name] = client.post(
            f"/pairings/{old_id}/{new_id}", json={"verdict": "paired"}
        ).status_code

    threads = [
        threading.Thread(target=settle, args=("alice", first_new_id)),
        threading.Thread(target=settle, args=("bob", second_new_id)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return Counter(outcomes.values()), outcomes


def _live_paired(driver, database):
    records, _, _ = driver.execute_query(
        "MATCH (d:PairingDecision {verdict: 'paired'}) "
        "RETURN count(d) AS total, collect(d.new_obligation_id) AS partners",
        database_=database,
    )
    return records[0]


def _lock_count(driver, database):
    records, _, _ = driver.execute_query(
        "MATCH (lock:PairingLock) RETURN count(lock) AS total", database_=database
    )
    return records[0]["total"]


@pytest.mark.integration
def test_two_concurrent_paired_verdicts_on_one_clause_cannot_both_land(
    client_with_auth, monkeypatch
):
    """The 409 has to hold under concurrency, and co-locating the read with the
    write does not make it.

    Neo4j is read-committed and takes no locks for reads, and two verdicts on
    one clause MERGE two *different* `:PairingDecision` nodes — so there is no
    node the two transactions share and nothing for either to block on. Without
    the edition-pair lock both requests answer 200 and the graph is left
    holding two live `paired` verdicts on one clause. Re-reading the conflict
    *after* recording does not fix it either: both transactions stay blind to
    the other's uncommitted writes right up to commit.

    This is the **MERGE-create** half of the lock: `clean_graph` empties the
    graph before every integration test, so no `:PairingLock` exists when these
    two requests arrive and the blocking is done by the uniqueness constraint's
    index entry. The match half — every verdict after the first in an edition
    pair, which is the production-normal case — is the test below.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW), ("5.1", RIVAL)],
    )

    assert _lock_count(driver, database) == 0, (
        "this test is the MERGE-create path; a pre-existing lock would make it "
        "the other one and leave the create path uncovered"
    )

    statuses, outcomes = _race_two_paired_verdicts(
        client_with_auth,
        monkeypatch,
        old_id=old_ids[BLANK_OLD],
        first_new_id=new_ids[BLANK_NEW],
        second_new_id=new_ids[RIVAL],
    )

    assert statuses == Counter([200, 409]), outcomes

    # The assertion that matters is the graph's, not the status codes'. A
    # second live `paired` verdict on one clause is the state the diff cannot
    # arbitrate: the first pops the shared clause, the second's lookup misses,
    # and a reviewer's verdict is reported as a pass-1 pre-emption in
    # `pairings_unapplied`.
    live = _live_paired(driver, database)
    assert live["total"] == 1, live["partners"]


@pytest.mark.integration
def test_a_race_against_an_existing_lock_node_is_also_refused(
    client_with_auth, monkeypatch
):
    """The lock's other half, and the one production actually spends its time
    on.

    `ACQUIRE_PAIR_LOCK` blocks by two different mechanisms depending on whether
    the lock node exists. On **create** — the only state a test starting from
    `clean_graph` can reach — the uniqueness constraint's index entry does the
    blocking. On **match**, which is every verdict after the first in an edition
    pair, the index entry is not touched and the only thing taking an exclusive
    lock is the `SET`: a MERGE that merely matches need not lock what it found.

    So the `SET` was load-bearing and unpinned. Measured with it removed: the
    test above passes 5/5 on an empty graph, while this race against a
    pre-existing lock gives `statuses={'alice': 200, 'bob': 200}
    live_paired=2 locks=1` — two live `paired` verdicts, one lock node, 5/5.
    Anyone deleting the `SET` as decoration would have kept the whole suite
    green and left the second reviewer of every edition pair unprotected.

    The lock here is created by a real prior verdict rather than seeded, so
    what is under test is the sequence a second reviewer actually meets. The
    prior verdict is `distinct` on a different pair: it takes the lock through
    the production path without leaving a live `paired` verdict that would
    confound the conflict check.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD), ("3.3", RIVAL_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW), ("5.1", RIVAL)],
    )

    prior = client_with_auth.post(
        f"/pairings/{old_ids[RIVAL_OLD]}/{new_ids[RIVAL]}",
        json={"verdict": "distinct", "rationale": "unrelated duties"},
    )
    assert prior.status_code == 200, prior.text

    # The whole point of the test: the racing verdicts below must find the lock
    # node already there, so `ACQUIRE_PAIR_LOCK` matches instead of creating and
    # the `SET` is the only thing that can serialise them.
    assert _lock_count(driver, database) == 1, (
        "a prior verdict in this edition pair must have left its lock node "
        "behind, or this test is the create path again"
    )

    statuses, outcomes = _race_two_paired_verdicts(
        client_with_auth,
        monkeypatch,
        old_id=old_ids[BLANK_OLD],
        first_new_id=new_ids[BLANK_NEW],
        second_new_id=new_ids[RIVAL],
    )

    assert statuses == Counter([200, 409]), outcomes

    live = _live_paired(driver, database)
    assert live["total"] == 1, live["partners"]

    # Still one lock node: a second one for the same key would mean the two
    # transactions had locked different nodes, which is the unconstrained
    # failure mode wearing a passing status code.
    assert _lock_count(driver, database) == 1


@pytest.mark.integration
def test_a_middle_edition_pairs_into_both_adjacent_pairs(client_with_auth):
    """The scope on the 409 is what makes this legal. B's clause pairs to its
    A-predecessor and to its C-successor — the very case the MANDATES-scoped
    read exists to keep separate — and an unscoped conflict rule would refuse
    the second verdict and prescribe destroying the first."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    a_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", BLANK_OLD)],
    )
    b_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", BLANK_NEW)],
    )
    c_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2022",
        entries=[("5.1", RIVAL)],
    )

    a_to_b = client_with_auth.post(
        f"/pairings/{a_ids[BLANK_OLD]}/{b_ids[BLANK_NEW]}",
        json={"verdict": "paired"},
    )
    b_to_c = client_with_auth.post(
        f"/pairings/{b_ids[BLANK_NEW]}/{c_ids[RIVAL]}",
        json={"verdict": "paired"},
    )

    assert a_to_b.status_code == 200
    assert b_to_c.status_code == 200


@pytest.mark.integration
def test_a_distinct_pair_stays_reachable_after_a_rediff(client_with_auth):
    """Reversal needs no candidate edge. A distinct-settled pair is excluded
    from recording, so after the next diff no edge re-asks the question — but
    the queue still returns it, marked settled, and a paired POST on it
    succeeds, because admissibility never depended on the edge."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )

    settled = client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "distinct", "rationale": "different duties"},
    )
    assert settled.status_code == 200

    body = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    ).json()

    assert len(body["settled"]) == 1
    row = body["settled"][0]
    assert row["verdict"] == "distinct"
    assert row["actor"] == "tester"
    assert row["old"]["obligation_id"] == old_ids[REWORDED_OLD]
    assert row["new"]["obligation_id"] == new_ids[REWORDED_NEW]
    assert body["items"] == []
    assert body["pending"] == 0

    # The settled row has to be renderable on its own. `items` is empty here —
    # a settled pair is deliberately never re-recorded as a candidate — so
    # there is no candidate row to borrow the statements from, and ids alone
    # would leave a screen nothing to draw and a reviewer no way back to the
    # verdict they want to undo. The document name in particular: without it a
    # screen has to split `version_id` on '@' and guess.
    assert row["old"]["document"] == "pol"
    assert row["new"]["document"] == "pol"
    assert row["old"]["statement"] == REWORDED_OLD
    assert row["new"]["statement"] == REWORDED_NEW
    assert row["old"]["version_id"] == "pol@2018"
    assert row["new"]["version_id"] == "pol@2020"
    assert row["old"]["section_path"] == ["3.2"]
    assert row["new"]["section_path"] == ["4.1"]

    reversed_verdict = client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "paired"},
    )
    assert reversed_verdict.status_code == 200
    assert reversed_verdict.json()["verdict"] == "paired"


def test_the_pairing_payloads_carry_exactly_these_fields():
    """Not a test of the field names. A test that changing one is deliberate.

    `frontend/src/api/types.ts` declares `PairingCandidate`, `PairingSettled`,
    `PairingVerdictRecorded` and `PairingQueue` by hand, and nothing checks the
    two declarations against each other. TypeScript catches one direction only:
    a stale screen meeting a renamed `types.ts` fails `tsc` with TS2339. A field
    ADDED here and not mirrored there is silent in both languages — the screen
    cannot read what it does not declare, and no test anywhere goes red. Adding
    one to `PairingQueueOut` was measured on this branch against a live stack:
    59 frontend tests stayed green.

    Every other test in this file reads these payloads by key and so pins the
    names too, but each does it while asking about something else and none says
    where the other half of the mirror lives. Changing these sets is fine;
    changing one without opening `types.ts` is the defect. `ReviewQueueOut` has
    carried the same guard since STORY-090.
    """
    assert set(PairingCandidateOut.model_fields) == {
        "old",
        "new",
        "confidence",
        "rationale",
        "outcome",
        "taken_by",
    }
    assert set(PairingSettledOut.model_fields) == {
        "old",
        "new",
        "verdict",
        "actor",
        "rationale",
    }
    assert set(PairingVerdictOut.model_fields) == {
        "old_id",
        "new_id",
        "verdict",
        "actor",
    }
    assert set(PairingQueueOut.model_fields) == {
        "items",
        "settled",
        "pairings_unapplied",
        "pending",
        "pending_by_outcome",
    }


@pytest.mark.integration
def test_a_settled_pair_carries_the_reason_it_was_settled_with(client_with_auth):
    """The settled list is the only route back to a recorded verdict, and
    reversing one overwrites `rationale` unconditionally. Without the reason on
    the row, a screen's reason box starts empty and posts that empty string on
    the reviewer's behalf — wiping the justification of the decision they are
    reversing, having never been shown it. Empty travels as "", not as a
    missing field: "recorded with no reason" and "not asked" are different
    answers.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD), ("5.1", BLANK_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW), ("5.1", BLANK_NEW)],
    )

    assert client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "distinct", "rationale": "competition, not acquisition"},
    ).status_code == 200
    assert client_with_auth.post(
        f"/pairings/{old_ids[BLANK_OLD]}/{new_ids[BLANK_NEW]}",
        json={"verdict": "distinct"},
    ).status_code == 200

    settled = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    ).json()["settled"]

    reasons = {
        (row["old"]["obligation_id"], row["new"]["obligation_id"]): row["rationale"]
        for row in settled
    }
    assert reasons[(old_ids[REWORDED_OLD], new_ids[REWORDED_NEW])] == (
        "competition, not acquisition"
    )
    assert reasons[(old_ids[BLANK_OLD], new_ids[BLANK_NEW])] == ""


@pytest.mark.integration
def test_a_decision_recorded_without_a_reason_still_lists(client_with_auth):
    """A `:PairingDecision` can exist with no `rationale` property at all: the
    migration copies the reason off the `:LinkDecision` it converts, and setting
    a property to null in Cypher removes it. The settled list is the only route
    back to a recorded verdict, so a row that cannot be serialised takes the
    whole queue down — a 500 where a reviewer needed the list most.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    old_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2018",
        entries=[("3.2", REWORDED_OLD)],
    )
    new_ids = _seed(
        driver, database, doc_slug="pol", version_id="pol@2020",
        entries=[("4.1", REWORDED_NEW)],
    )
    old_id, new_id = old_ids[REWORDED_OLD], new_ids[REWORDED_NEW]
    driver.execute_query(
        "CREATE (:PairingDecision {key: $key, old_obligation_id: $old_id, "
        "new_obligation_id: $new_id, verdict: 'distinct', actor: 'migration', "
        "at: datetime()})",
        {"key": pairing_key(old_id, new_id), "old_id": old_id, "new_id": new_id},
        database_=database,
    )

    response = client_with_auth.get(
        "/pairings/queue",
        params={"from_version_id": "pol@2018", "to_version_id": "pol@2020"},
    )

    assert response.status_code == 200
    assert response.json()["settled"][0]["rationale"] == ""
