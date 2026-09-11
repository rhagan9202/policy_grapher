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

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    WORD_MODALITIES,
    ExtractedObligation,
    Modality,
)
from policy_grapher.links.pairing import pairing_key
from policy_grapher.obligations import write_obligations

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


def _seed(driver, database, *, doc_slug, version_id, entries):
    """`entries` is (section, statement) pairs; returns {statement: obligation_id}.

    Editions are created bare — no effective_date, no ingested_at — so ordering
    rests on the version_id tie-breaker; choose ids that sort chronologically.
    """
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"slug": doc_slug, "vid": version_id},
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

    assert body["settled"] == [
        {
            "old_id": old_ids[REWORDED_OLD],
            "new_id": new_ids[REWORDED_NEW],
            "verdict": "distinct",
            "actor": "tester",
        }
    ]
    assert body["items"] == []
    assert body["pending"] == 0

    reversed_verdict = client_with_auth.post(
        f"/pairings/{old_ids[REWORDED_OLD]}/{new_ids[REWORDED_NEW]}",
        json={"verdict": "paired"},
    )
    assert reversed_verdict.status_code == 200
    assert reversed_verdict.json()["verdict"] == "paired"
