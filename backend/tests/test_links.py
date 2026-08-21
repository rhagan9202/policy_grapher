import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.propose import (
    content_words,
    designators,
    propose_links,
    score_pair,
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
UNRELATED = "Travel vouchers may be submitted electronically before departure."


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
    """Naming a version as its own candidate must not link every clause to itself."""
    section_path = _seed_version(
        clean_graph, database, version_id="org", statements=[ORG, HIGHER]
    )

    with clean_graph.session(database=database) as session:
        session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["org"],
            proposer="lexical-v1",
        )

    self_id = obligation_id("org", section_path, ORG)
    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    assert all(r["source"] != r["target"] for r in records)
    assert all(r["source"] != self_id or r["target"] != self_id for r in records)
