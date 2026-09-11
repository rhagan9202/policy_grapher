import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.links.decisions import (
    LINK_SCHEMA,
    DecisionSchema,
    decision_key,
    record_decision,
    replay_decisions,
)
from policy_grapher.links.pairing import (
    PAIRING_SCHEMA,
    pairing_key,
    record_pairing,
)
from policy_grapher.links.propose import (
    content_words,
    designators,
    propose_links,
    score_pair,
    score_pairing,
)
from policy_grapher.obligations import write_obligations

# --- pure scoring ------------------------------------------------------------


def test_a_designator_is_recognised_inside_a_sentence():
    """The reference parser only matches a whole reference-list entry. An
    obligation cites in running prose."""
    assert designators("Components must comply with DoDI 5000.88 when assessing.") == {
        "DoDI 5000.88"
    }


def test_several_designators_are_all_recognised():
    found = designators("See DoDD 5000.01 and DoDM 8180.01 for detail.")
    assert found == {"DoDD 5000.01", "DoDM 8180.01"}


def test_prose_without_a_designator_yields_none():
    assert designators("The Director shall notify the Comptroller.") == set()


def test_content_words_drop_the_words_every_obligation_shares():
    """'shall', 'the', 'of' appear in nearly every obligation. Counting them as
    overlap would make every pair look related to every other."""
    words = content_words("The Director shall notify the Comptroller of a breach.")
    assert "director" in words and "comptroller" in words and "breach" in words
    assert "the" not in words and "shall" not in words and "of" not in words


def test_an_identical_statement_scores_at_the_top():
    statement = "The Program Manager must document the cybersecurity strategy."
    result = score_pair(statement, statement)
    assert result is not None
    assert result.confidence == 1.0


def test_two_unrelated_obligations_do_not_score():
    assert (
        score_pair(
            "Travel vouchers may be submitted electronically.",
            "The Program Manager must document the cybersecurity strategy.",
        )
        is None
    )


def test_a_shared_designator_raises_confidence():
    """Two clauses citing the same issuance are related evidence a word count misses."""
    org = "The Director shall assess risk in accordance with DoDI 5000.88."
    higher = "Components must comply with DoDI 5000.88 when assessing risk."

    with_designator = score_pair(org, higher)
    without = score_pair(
        org.replace(" in accordance with DoDI 5000.88", ""),
        higher.replace(" with DoDI 5000.88", ""),
    )

    assert with_designator is not None and without is not None
    assert with_designator.confidence > without.confidence


def test_the_rationale_names_what_the_two_have_in_common():
    """A reviewer decides from this sentence, so it has to say something."""
    result = score_pair(
        "The Director shall assess cybersecurity risk in accordance with DoDI 5000.88.",
        "Components must comply with DoDI 5000.88 when assessing cybersecurity risk.",
    )
    assert result is not None
    assert "DoDI 5000.88" in result.rationale
    assert "cybersecurity" in result.rationale


def test_confidence_never_exceeds_one():
    """It is written onto an edge and read as a probability by the queue."""
    org = "Comply with DoDI 5000.88 and DoDD 5000.01 and DoDM 8180.01."
    result = score_pair(org, org)
    assert result is not None
    assert result.confidence <= 1.0


def test_the_proposal_rationale_wording_is_pinned_verbatim():
    """This sentence is stored on every `IMPLEMENTS_PROPOSED` edge and shown in
    the review queue; the pairing split rewrites the *pairing* sentence, not
    this one. Byte-for-byte on purpose — a looser test would pass a paraphrase
    that still changes what live proposals say."""
    result = score_pair(
        "The Director shall assess cybersecurity risk in accordance with DoDI 5000.88.",
        "Components must comply with DoDI 5000.88 when assessing cybersecurity risk.",
    )
    assert result is not None
    assert result.rationale == (
        "Both cite DoDI 5000.88; they share 60% of the shorter clause's "
        "distinctive wording (cybersecurity, dodi, risk). Confirm the org "
        "clause actually discharges the higher duty before approving."
    )


def test_score_pairing_and_score_pair_agree_on_the_measure():
    """One measurement serves both reviewers. The shorter clause here is wholly
    contained in the longer, which only the min() denominator scores at 1.0 —
    so this pins the denominator as well as the agreement."""
    after = (
        "The Program Manager shall document the cybersecurity strategy for "
        "each acquisition program."
    )
    before = "The Program Manager must document the cybersecurity strategy."

    paired = score_pairing(after, before)
    proposed = score_pair(after, before)

    assert paired is not None and proposed is not None
    assert paired.confidence == proposed.confidence
    assert paired.confidence == 1.0


def test_score_pairing_keeps_the_proposers_floor():
    """Both statements carry content words but share none, which lands on the
    `MIN_CONFIDENCE` floor rather than the empty-statement branch. Below the
    floor there is nothing a rationale could honestly say the clauses share."""
    assert (
        score_pairing(
            "The Program Manager must document the cybersecurity strategy.",
            "Travel vouchers may be submitted electronically.",
        )
        is None
    )


def test_the_pairing_rationale_asks_the_pairing_question():
    """The reviewer on the pairing screen decides whether one clause is the
    other reworded — not whether anything discharges anything. The implements
    advisory would tell them to verify a relationship nobody is claiming."""
    result = score_pairing(
        "The Director shall assess cybersecurity risk in accordance with DoDI 5000.88.",
        "Components must comply with DoDI 5000.88 when assessing cybersecurity risk.",
    )
    assert result is not None
    assert "DoDI 5000.88" in result.rationale
    assert "cybersecurity" in result.rationale
    assert "reworded" in result.rationale
    assert "discharges" not in result.rationale
    assert "approving" not in result.rationale


# --- proposing into the graph ------------------------------------------------


def _seed_version(driver, database, *, version_id, statements):
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $name}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": version_id, "name": version_id.upper(), "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    obligations = [
        ExtractedObligation(
            statement=s,
            modality=Modality.MUST,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        )
        for s in statements
    ]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=obligations,
        )
    return chunk.section_path


HIGHER = "Components must document the cybersecurity strategy in the engineering plan."
ORG = "The Program Manager must document the cybersecurity strategy in the program plan."
UNRELATED = "Travel vouchers must be submitted electronically before departure."


def _seed_pair(driver, database, *, org=ORG, higher=HIGHER):
    _seed_version(driver, database, version_id="higher", statements=[higher])
    return _seed_version(driver, database, version_id="org", statements=[org])


@pytest.mark.integration
def test_a_proposal_carries_its_confidence_rationale_and_proposer(
    clean_graph, database
):
    _seed_pair(clean_graph, database)

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["higher"],
            proposer="lexical-v1",
        )

    assert written == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Obligation)-[r:IMPLEMENTS_PROPOSED]->(:Obligation) "
        "RETURN r.confidence AS confidence, r.rationale AS rationale, "
        "r.proposer AS proposer",
        database_=database,
    )
    assert records[0]["proposer"] == "lexical-v1"
    assert 0.0 < records[0]["confidence"] <= 1.0
    assert "cybersecurity" in records[0]["rationale"]


@pytest.mark.integration
def test_proposing_never_creates_an_implements_edge(clean_graph, database):
    """The invariant the whole phase rests on. A machine guess must be unable to
    read as an approved fact — not by remembering to filter, but by construction."""
    _seed_pair(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["higher"],
            proposer="lexical-v1",
        )

    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_proposing_twice_creates_one_edge(clean_graph, database):
    _seed_pair(clean_graph, database)

    with clean_graph.session(database=database) as session:
        for _ in range(2):
            session.execute_write(
                propose_links,
                org_version_id="org",
                candidate_version_ids=["higher"],
                proposer="lexical-v1",
            )

    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS_PROPOSED]->() RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_an_obligation_with_no_counterpart_yields_no_proposal(clean_graph, database):
    """An empty queue is a correct outcome, not a failure to try."""
    _seed_pair(clean_graph, database, org=UNRELATED)

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["higher"],
            proposer="lexical-v1",
        )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS_PROPOSED]->() RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_an_obligation_is_never_proposed_against_itself(clean_graph, database):
    """Naming a version as its own candidate must not link every clause to itself.

    Counted, not shaped. The assertion used to read "no row has source ==
    target", which an empty result satisfies vacuously — and this result is now
    always empty: a version has exactly one parent :Document, so every pair in
    this fixture is also a same-document pair and the document check covers all
    of them, whichever check the loop reaches first.

    Two mutants tell the forms apart, both run. Deleting the document check
    alone leaves the two cross-statement pairs, which the row form passed
    because neither row is self-directed and the count catches at 2. Deleting
    both leaves 4, which both forms catch. Deleting the self-comparison alone
    is caught by neither — the document check empties the result either way —
    and no test here can close that, which is why `propose.py` says at the line
    itself what keeps it.
    """
    _seed_version(clean_graph, database, version_id="org", statements=[ORG, HIGHER])

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org"],
            proposer="lexical-v1",
        )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    assert records == []


# --- decisions and promotion -------------------------------------------------


def _decide(driver, database, *, source, target, verdict, actor="alice", rationale="r"):
    with driver.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id=source,
            target_id=target,
            verdict=verdict,
            actor=actor,
            rationale=rationale,
        )


def _replay(driver, database):
    with driver.session(database=database) as session:
        return session.execute_write(replay_decisions)


def _implements(driver, database):
    records, _, _ = driver.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    return {(r["source"], r["target"]) for r in records}


def _proposed_pair(driver, database):
    records, _, _ = driver.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    return records[0]["source"], records[0]["target"]


def _seed_proposal(driver, database):
    _seed_pair(driver, database)
    with driver.session(database=database) as session:
        session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["higher"],
            proposer="lexical-v1",
        )
    return _proposed_pair(driver, database)


def test_the_decision_key_is_directional():
    """'A implements B' is not 'B implements A'. A symmetric key would let a
    verdict on one direction silently decide the other."""
    assert decision_key("a", "b") != decision_key("b", "a")


def test_the_decision_key_is_stable():
    assert decision_key("a", "b") == decision_key("a", "b")


@pytest.mark.integration
def test_approving_promotes_the_proposal_and_leaves_it_in_place(clean_graph, database):
    """The proposal is derived evidence of how the link was found; promotion adds
    the human's edge beside it rather than consuming it."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")

    promoted = _replay(clean_graph, database)

    assert promoted["promoted"] == 1
    assert _implements(clean_graph, database) == {(source, target)}
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS_PROPOSED]->() RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_rejecting_promotes_nothing_and_stays_rejected_across_replays(
    clean_graph, database
):
    """A rebuild that resurrects a rejected link silently re-adds work a human
    already did and dismissed — worse than forgetting an approval."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="reject")

    first = _replay(clean_graph, database)
    second = _replay(clean_graph, database)

    assert first["suppressed"] == 1
    assert second["suppressed"] == 1
    assert _implements(clean_graph, database) == set()


@pytest.mark.integration
def test_a_decision_records_who_decided_and_when(clean_graph, database):
    source, target = _seed_proposal(clean_graph, database)
    _decide(
        clean_graph, database, source=source, target=target,
        verdict="approve", actor="alice", rationale="Discharges the duty.",
    )

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.actor AS actor, d.at AS at, "
        "d.verdict AS verdict, d.rationale AS rationale",
        database_=database,
    )
    assert records[0]["actor"] == "alice"
    assert records[0]["verdict"] == "approve"
    assert records[0]["rationale"] == "Discharges the duty."
    assert records[0]["at"] is not None


@pytest.mark.integration
def test_re_deciding_updates_the_verdict_rather_than_adding_a_second(
    clean_graph, database
):
    """A reviewer who changes their mind must leave one current verdict, not two
    contradictory records for a replay to choose between."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")
    _decide(
        clean_graph, database, source=source, target=target,
        verdict="reject", actor="bob",
    )

    _replay(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total, "
        "collect(d.verdict) AS verdicts, collect(d.actor) AS actors",
        database_=database,
    )
    assert records[0]["total"] == 1
    assert records[0]["verdicts"] == ["reject"]
    assert records[0]["actors"] == ["bob"]
    assert _implements(clean_graph, database) == set()


@pytest.mark.integration
def test_reversing_a_rejection_promotes_it(clean_graph, database):
    """The other direction of the same path: reject then approve must promote."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="reject")
    _replay(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")

    _replay(clean_graph, database)

    assert _implements(clean_graph, database) == {(source, target)}


@pytest.mark.integration
def test_replay_is_idempotent(clean_graph, database):
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")

    first = _replay(clean_graph, database)
    second = _replay(clean_graph, database)

    assert first == second
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_an_approval_whose_obligations_are_gone_is_reported_not_dropped(
    clean_graph, database
):
    """After a re-extraction that no longer produces one side, the decision is
    still a fact a human established. Replay cannot promote it, and must say so
    rather than passing over it in silence."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="approve")
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) DETACH DELETE o",
        {"id": target},
        database_=database,
    )

    result = _replay(clean_graph, database)

    assert result["promoted"] == 0
    assert result["unpromotable"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_an_unknown_verdict_is_refused(clean_graph, database):
    """The verdict vocabulary is closed: replay branches on it, and a value it
    does not know would be silently ignored — an approval that never promotes."""
    source, target = _seed_proposal(clean_graph, database)
    with pytest.raises(ValueError, match="verdict"):
        _decide(
            clean_graph, database, source=source, target=target, verdict="maybe"
        )


# --- re-pointing decisions across a change of identity (ADR-027) ------------


@pytest.mark.integration
def test_a_decision_survives_its_obligations_being_re_keyed(clean_graph, database):
    """The identity of an obligation contains its section_path, so a chunker
    change re-keys it and strands the verdict a human recorded against it. The
    decision is a fact a human established (ADR-014); a re-key does not make it
    untrue, and ADR-027 requires the rebuild to carry it across."""
    from policy_grapher.links.decisions import repoint_decisions

    old_source, old_target = "old-source-id", "old-target-id"
    new_source, new_target = "new-source-id", "new-target-id"

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id=old_source,
            target_id=old_target,
            verdict="approve",
            actor="reviewer",
            rationale="checked against the source",
        )

        repointed = session.execute_write(
            repoint_decisions,
            before={old_source: "the director shall report", old_target: "components shall comply"},
            after={"the director shall report": new_source, "components shall comply": new_target},
        )

    assert repointed == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.source_obligation_id AS s, "
        "d.target_obligation_id AS t, d.key AS key, d.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["s"] == new_source
    assert records[0]["t"] == new_target
    assert records[0]["key"] == decision_key(new_source, new_target)
    # The verdict is what must survive. Re-pointing that dropped it would be
    # worse than not re-pointing at all.
    assert records[0]["verdict"] == "approve"


@pytest.mark.integration
def test_a_repoint_that_would_collide_leaves_the_existing_verdict_alone(clean_graph, database):
    """Two human verdicts must never be silently merged into one. If a stale
    decision would re-key onto a decision that already exists, the existing one
    wins and the stale one is left for the unpromotable count."""
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision, source_id="old-a", target_id="old-b",
            verdict="approve", actor="reviewer", rationale="stale",
        )
        session.execute_write(
            record_decision, source_id="new-a", target_id="new-b",
            verdict="reject", actor="reviewer", rationale="current",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-a", "statement two": "new-b"},
        )

    assert repointed == 0

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision {key: $key}) RETURN d.verdict AS verdict",
        {"key": decision_key("new-a", "new-b")},
        database_=database,
    )
    assert records[0]["verdict"] == "reject", "the existing verdict must win"


@pytest.mark.integration
def test_a_statement_two_obligations_share_repoints_neither(clean_graph, database):
    """A statement is only a handle on an obligation while it names exactly one.

    `obligation_id` hashes `version_id | section_path | statement`, so the same
    sentence in two sections is two distinct nodes with two distinct ids. Mapping
    either of them through that shared statement picks whichever id the rebuild
    happened to record for it, which is a coin toss between two obligations — and
    ADR-027's own invariant is that a human's verdict is never silently moved onto
    something nobody judged. An ambiguous statement therefore repairs nothing and
    falls through to the unpromotable count.
    """
    from policy_grapher.links.decisions import repoint_decisions

    shared = "the director shall report"
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision, source_id="old-a", target_id="target-one",
            verdict="approve", actor="reviewer", rationale="the one in section 3",
        )
        session.execute_write(
            record_decision, source_id="old-b", target_id="target-two",
            verdict="reject", actor="reviewer", rationale="the one in section 9",
        )

        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": shared, "old-b": shared},
            after={shared: "new-a"},
        )

    assert repointed == 0

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.source_obligation_id AS s, "
        "d.target_obligation_id AS t, d.key AS key, d.verdict AS verdict "
        "ORDER BY d.source_obligation_id",
        database_=database,
    )
    assert [(r["s"], r["t"], r["verdict"]) for r in records] == [
        ("old-a", "target-one", "approve"),
        ("old-b", "target-two", "reject"),
    ]
    assert [r["key"] for r in records] == [
        decision_key("old-a", "target-one"),
        decision_key("old-b", "target-two"),
    ]


@pytest.mark.integration
def test_two_repoints_that_would_collide_with_each_other_do_not_abort_the_batch(
    clean_graph, database
):
    """`link_decision_key_unique` constrains `:LinkDecision.key`, so two moves in
    one batch that compute the same new key cannot both be written. Screening each
    proposed key only against the decisions that existed *before* the batch lets
    both pass, and `APPLY_REPOINT` then violates the constraint and rolls the whole
    rebuild back — the one collision ADR-027 does not already handle (STORY-074).
    The batch has to behave the way a collision against a pre-existing decision
    does: one move lands, the loser is left for `unpromotable`.
    """
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision, source_id="old-a", target_id="target",
            verdict="approve", actor="reviewer", rationale="first",
        )
        session.execute_write(
            record_decision, source_id="old-b", target_id="target",
            verdict="approve", actor="reviewer", rationale="second",
        )

        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-x", "statement two": "new-x"},
        )

    assert repointed == 1, "one move lands; the colliding one is left unrepaired"

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.source_obligation_id AS s, d.key AS key",
        database_=database,
    )
    assert len(records) == 2, "both human verdicts still exist"
    moved = [r for r in records if r["key"] == decision_key("new-x", "target")]
    assert len(moved) == 1
    stranded = [r for r in records if r["key"] != decision_key("new-x", "target")]
    assert stranded[0]["s"] in {"old-a", "old-b"}
    assert stranded[0]["key"] == decision_key(stranded[0]["s"], "target")


# --- STORY-076: a stranded rejection is counted too ----------------------------


@pytest.mark.integration
def test_a_rejection_the_replay_cannot_apply_is_counted(clean_graph, database):
    """`UNPROMOTABLE` filters `{verdict: 'approve'}`, so a rejection whose
    obligations a re-extraction moved beyond repair was counted by nothing.

    The asymmetry is worse than it looks. An approval that cannot be applied
    leaves a link missing, and the reviewer meets it again in the queue. A
    rejection that cannot be applied leaves a **suppression nobody is applying**:
    the proposal comes back and the reviewer has no way to know they already
    refused it. The verdict is not merely lost, it is silently reversed.
    """
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="reject")
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) DETACH DELETE o",
        {"id": target},
        database_=database,
    )

    result = _replay(clean_graph, database)

    assert result["rejections_stranded"] == 1
    # Not folded into `unpromotable`: that name means "was going to promote and
    # could not", and a rejection was never going to promote anything.
    assert result["unpromotable"] == 0


@pytest.mark.integration
def test_the_two_stranded_counts_move_independently(clean_graph, database):
    """A stranded approval must not increment the rejection count or vice versa —
    otherwise one number is doing two jobs and neither can be read."""
    source_a, target_a = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source_a, target=target_a, verdict="approve")
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) DETACH DELETE o",
        {"id": target_a},
        database_=database,
    )

    result = _replay(clean_graph, database)

    assert result["unpromotable"] == 1
    assert result["rejections_stranded"] == 0


@pytest.mark.integration
def test_a_rejection_the_replay_can_still_apply_is_not_stranded(
    clean_graph, database
):
    """The count is about loss, not about rejections in general."""
    source, target = _seed_proposal(clean_graph, database)
    _decide(clean_graph, database, source=source, target=target, verdict="reject")

    result = _replay(clean_graph, database)

    assert result["rejections_stranded"] == 0
    assert result["suppressed"] >= 1


# --- IMPLEMENTS is cross-document only (pairing design §1) ---------------------


def _seed_second_edition(driver, database, *, of, version_id, statements):
    """A second edition of a document `_seed_version` already created.

    `_seed_version` keys one document per version id, so the same-document
    shape — two editions under one :Document — has to be built here.
    """
    driver.execute_query(
        "MATCH (d:Document {slug: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": of, "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    obligations = [
        ExtractedObligation(
            statement=s,
            modality=Modality.MUST,
            actor=None,
            deadline=None,
            conditions=None,
            confidence=0.9,
        )
        for s in statements
    ]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=obligations,
        )


@pytest.mark.integration
def test_a_pair_inside_one_document_is_never_proposed(clean_graph, database):
    """Two editions of one instrument are the pairing question, not the
    implements one — an edition does not discharge its predecessor. These two
    statements produce a proposal across two documents elsewhere in this file,
    so a written count of zero here can only be the document skip."""
    _seed_version(clean_graph, database, version_id="org", statements=[ORG])
    _seed_second_edition(
        clean_graph, database, of="org", version_id="org@2024", statements=[HIGHER]
    )

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org@2024"],
            proposer="lexical-v1",
        )

    assert written == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS_PROPOSED]->() RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_the_cross_document_pair_is_still_proposed_beside_a_skipped_one(
    clean_graph, database
):
    """The skip must not be a clause too wide. The same statement is offered
    from a sibling edition and from another document; exactly the
    cross-document pair survives."""
    _seed_version(clean_graph, database, version_id="org", statements=[ORG])
    _seed_second_edition(
        clean_graph, database, of="org", version_id="org@2024", statements=[HIGHER]
    )
    _seed_version(clean_graph, database, version_id="higher", statements=[HIGHER])

    with clean_graph.session(database=database) as session:
        written = session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org@2024", "higher"],
            proposer="lexical-v1",
        )

    assert written == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Obligation)-[:IMPLEMENTS_PROPOSED]->(t:Obligation)"
        "<-[:MANDATES]-(v:DocumentVersion) RETURN v.version_id AS version",
        database_=database,
    )
    assert [r["version"] for r in records] == ["higher"]


# --- the repoint refactor serves the pairing vocabulary too (spec §5) ---------


@pytest.mark.integration
def test_a_pairing_decision_survives_its_obligations_being_re_keyed(
    clean_graph, database
):
    """`repoint_decisions` is parameterised by `DecisionSchema` so the pairing
    vocabulary rides the same ADR-027 repair path as `:LinkDecision`. Under
    `PAIRING_SCHEMA` it must read, re-key and rewrite `:PairingDecision` nodes —
    a label or property name hardcoded anywhere in the path would silently
    repoint nothing and strand the verdict."""
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id="old-old-id",
            new_id="old-new-id",
            verdict="paired",
            actor="reviewer",
            rationale="the reworded duty",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={
                "old-old-id": "the director shall report",
                "old-new-id": "the director reports",
            },
            after={
                "the director shall report": "new-old-id",
                "the director reports": "new-new-id",
            },
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.key AS key, p.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old"] == "new-old-id"
    assert records[0]["new"] == "new-new-id"
    assert records[0]["key"] == pairing_key("new-old-id", "new-new-id")
    # The verdict is what must survive. Re-pointing that dropped it would be
    # worse than not re-pointing at all.
    assert records[0]["verdict"] == "paired"


@pytest.mark.integration
def test_two_pairing_repoints_that_would_collide_do_not_abort_the_batch(
    clean_graph, database
):
    """`pairing_decision_key_unique` constrains `:PairingDecision.key` exactly as
    `link_decision_key_unique` constrains `:LinkDecision.key`, so the STORY-074
    hazard transfers whole: two moves in one batch computing the same new key
    cannot both be written, and screening each proposed key only against the
    pre-batch set would let `APPLY_REPOINT` violate the constraint and roll the
    caller's whole transaction back. Same resolution as a collision against a
    pre-existing decision: the first move lands, the loser is left unrepaired
    for `count_stranded_pairings`.
    """
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing, old_id="old-a", new_id="target",
            verdict="paired", actor="reviewer", rationale="first",
        )
        session.execute_write(
            record_pairing, old_id="old-b", new_id="target",
            verdict="distinct", actor="reviewer", rationale="second",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-x", "statement two": "new-x"},
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 1, "one move lands; the colliding one is left unrepaired"

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, p.key AS key",
        database_=database,
    )
    assert len(records) == 2, "both human verdicts still exist"
    moved = [r for r in records if r["key"] == pairing_key("new-x", "target")]
    assert len(moved) == 1
    # The winner's obligation id moved, not merely its key: a repair that
    # re-keyed without rewriting the property would leave a decision whose key
    # no longer describes the pair it points at, and every remaining assertion
    # here reads the loser, which is untouched by construction.
    assert moved[0]["old"] == "new-x"
    stranded = [r for r in records if r["key"] != pairing_key("new-x", "target")]
    assert stranded[0]["old"] in {"old-a", "old-b"}
    assert stranded[0]["key"] == pairing_key(stranded[0]["old"], "target")


@pytest.mark.integration
def test_a_pairing_repoint_that_would_collide_leaves_the_existing_verdict_alone(
    clean_graph, database
):
    """The *other* collision mode, and the one `EXISTING_KEYS` screens: not two
    moves racing inside one batch, but one move landing on a `:PairingDecision`
    that was already there before the batch began.

    Both modes end in the same violated constraint and the same rolled-back
    rebuild, and they are screened by two different pieces of code — the
    pre-batch read here, the growing `taken` set there — so covering one proves
    nothing about the other. Under a label hardcoded back to `:LinkDecision`,
    `EXISTING_KEYS` reads an empty set and this move is accepted onto a key
    another human verdict already holds.
    """
    from policy_grapher.links.decisions import repoint_decisions

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing, old_id="old-a", new_id="old-b",
            verdict="paired", actor="reviewer", rationale="stale",
        )
        session.execute_write(
            record_pairing, old_id="new-a", new_id="new-b",
            verdict="distinct", actor="reviewer", rationale="current",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-a", "statement two": "new-b"},
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 0

    # Both verdicts intact, the stale one left exactly where it was for
    # `count_stranded_pairings` to report. Asserting the whole pair rather than
    # only the winner: a repair that deleted the loser, or overwrote the
    # winner's verdict with it, would satisfy a check on either one alone.
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.verdict AS verdict, p.key AS key "
        "ORDER BY p.old_obligation_id",
        database_=database,
    )
    assert [(r["old"], r["new"], r["verdict"]) for r in records] == [
        ("new-a", "new-b", "distinct"),
        ("old-a", "old-b", "paired"),
    ]
    assert [r["key"] for r in records] == [
        pairing_key("new-a", "new-b"),
        pairing_key("old-a", "old-b"),
    ]


@pytest.mark.integration
def test_a_key_an_unrelated_link_decision_holds_does_not_strand_a_pairing(
    clean_graph, database
):
    """`EXISTING_KEYS` is scoped by label, and that is load-bearing rather than
    decorative: `decision_key` and `pairing_key` have byte-identical bodies, so
    a `:LinkDecision` can hold the exact key string a `:PairingDecision` is
    about to move onto. The two uniqueness constraints are per-label, so both
    keys may coexist, and the pairing verdict is perfectly repairable.

    Dropping the label from that query looks like a tidy — a key alone appears
    to identify a decision — and the failure it causes is silent and plausible:
    the pairing collides with a link decision that merely shares a hash input,
    is skipped, and is then reported to a reviewer as a verdict that could not
    be repaired. Nothing about the two decisions was related; only the label in
    that query stands between the reviewer and a false report.
    """
    from policy_grapher.links.decisions import repoint_decisions

    # The premise, asserted rather than assumed. If the two key functions ever
    # stop agreeing there is no collision left to screen and this test proves
    # nothing — it should be revisited then, not deleted, because the property
    # it guards is that `EXISTING_KEYS` never reads another label's keys.
    assert pairing_key("new-a", "new-b") == decision_key("new-a", "new-b")

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing, old_id="old-a", new_id="old-b",
            verdict="paired", actor="reviewer", rationale="the reworded duty",
        )
        # Unrelated in every way except the hash of its two ids.
        session.execute_write(
            record_decision, source_id="new-a", target_id="new-b",
            verdict="approve", actor="someone else", rationale="another question",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={"old-a": "statement one", "old-b": "statement two"},
            after={"statement one": "new-a", "statement two": "new-b"},
            schema=PAIRING_SCHEMA,
        )

    assert repointed == 1, "a foreign label's key is not this schema's collision"

    pairings, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.key AS key, p.verdict AS verdict",
        database_=database,
    )
    assert [(r["old"], r["new"], r["verdict"]) for r in pairings] == [
        ("new-a", "new-b", "paired")
    ]
    assert pairings[0]["key"] == pairing_key("new-a", "new-b")

    # And the link decision it now shares a key string with is untouched. Both
    # rows exist at once, which is what the per-label constraints permit and
    # what an unlabelled screen would have read as one decision.
    links, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.source_obligation_id AS s, "
        "d.target_obligation_id AS t, d.key AS key, d.verdict AS verdict",
        database_=database,
    )
    assert [(r["s"], r["t"], r["verdict"]) for r in links] == [
        ("new-a", "new-b", "approve")
    ]
    assert links[0]["key"] == decision_key("new-a", "new-b")


def _tagged_key(source_id: str, target_id: str) -> str:
    """A key function no real schema would use, so a repoint that calls a
    production key function instead of the schema's own is visible in the key
    it stores."""
    return f"tagged|{source_id}|{target_id}"


@pytest.mark.integration
def test_the_schemas_own_key_function_is_the_one_that_gets_used(
    clean_graph, database
):
    """`key_of` is one of `DecisionSchema`'s four contracted fields, and it is
    the only one nothing else can pin, because the two real key functions have
    byte-identical bodies: `decision_key` and `pairing_key` both sha256
    `f"{a}|{b}"`. A `repoint_decisions` that ignored `schema.key_of` and called
    either one directly computes the same string in every other test in this
    file, so the parameterisation would be accidentally redundant rather than
    observably correct. This schema's key function is distinguishable from both.
    """
    from policy_grapher.links.decisions import repoint_decisions

    tagged = DecisionSchema(
        label="PairingDecision",
        source_prop="old_obligation_id",
        target_prop="new_obligation_id",
        key_of=_tagged_key,
    )

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id="old-old-id", new_id="old-new-id",
            verdict="paired", actor="reviewer", rationale="the reworded duty",
        )
        repointed = session.execute_write(
            repoint_decisions,
            before={
                "old-old-id": "the director shall report",
                "old-new-id": "the director reports",
            },
            after={
                "the director shall report": "new-old-id",
                "the director reports": "new-new-id",
            },
            schema=tagged,
        )

    assert repointed == 1

    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.key AS key", database_=database
    )
    assert records[0]["key"] == "tagged|new-old-id|new-new-id"
    assert records[0]["key"] != pairing_key("new-old-id", "new-new-id")


def test_a_schema_refuses_a_label_or_property_that_is_not_an_identifier():
    """The three name fields are interpolated into Cypher as text, because
    Neo4j cannot parameterise a label or a property name. Refusing at
    construction is what makes the safety claim above those templates a property
    of the type rather than an observation about the two instances that happen
    to exist: `DecisionSchema(label=body["label"], ...)` would otherwise
    type-check and inject. The failure has to land here, where the value is
    still a Python string, not at query time where it is already statement text.
    """
    injections = [
        {"label": "LinkDecision) DETACH DELETE (d"},
        {"label": "Link Decision"},
        {"label": ""},
        {"source_prop": "source_obligation_id} REMOVE d:LinkDecision //"},
        {"target_prop": "target obligation id"},
    ]
    for override in injections:
        fields = {
            "label": "LinkDecision",
            "source_prop": "source_obligation_id",
            "target_prop": "target_obligation_id",
            "key_of": decision_key,
            **override,
        }
        with pytest.raises(ValueError, match="identifier"):
            DecisionSchema(**fields)

    # And the rule must not be one the real schemas cannot satisfy.
    assert LINK_SCHEMA.label == "LinkDecision"
    assert PAIRING_SCHEMA.label == "PairingDecision"
