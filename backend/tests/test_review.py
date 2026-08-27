"""The review queue: what a human sees, and what their verdict is recorded as."""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.links.propose import propose_links
from policy_grapher.obligations import write_obligations

HIGHER = "Components must document the cybersecurity strategy in the engineering plan."
ORG = "The Program Manager must document the cybersecurity strategy in the program plan."


def _seed_version(driver, database, *, version_id, name, statement):
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $name}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": version_id, "name": name, "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages(
        ["CHAPTER 2\n2.4. DUTIES.\nBody text.\n"], version_id=version_id
    )[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[
                ExtractedObligation(
                    statement=statement,
                    modality=Modality.MUST,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
            ],
        )


@pytest.fixture
def queued(client_with_auth):
    """One proposal, awaiting a verdict."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    _seed_version(
        driver, database, version_id="higher", name="DoDI 5000.88", statement=HIGHER
    )
    _seed_version(
        driver, database, version_id="org", name="ORG 1.0", statement=ORG
    )
    with driver.session(database=database) as session:
        assert (
            session.execute_write(
                propose_links,
                org_version_id="org",
                candidate_version_ids=["higher"],
                proposer="lexical-v1",
            )
            == 1
        )
    return client_with_auth


@pytest.mark.integration
def test_the_queue_shows_both_sides_with_their_citations(queued):
    """A reviewer cannot decide without knowing where each clause comes from:
    which document, which section, which page."""
    response = queued.get("/review/queue")
    assert response.status_code == 200

    item = response.json()["items"][0]
    assert item["source"]["statement"] == ORG
    assert item["target"]["statement"] == HIGHER
    assert item["target"]["document"] == "DoDI 5000.88"
    assert item["source"]["section_path"] == ["CHAPTER 2", "2.4"]
    assert item["source"]["page"] == 1
    assert item["target"]["page"] == 1
    assert item["confidence"] > 0
    assert "cybersecurity" in item["rationale"]
    assert item["proposer"] == "lexical-v1"


@pytest.mark.integration
def test_a_decided_pair_leaves_the_queue(queued):
    """The queue is what is *unreviewed*. A decided pair reappearing would ask a
    human to redo work they have already done."""
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    posted = queued.post(
        f"/review/{source}/{target}", json={"verdict": "approve", "rationale": "Yes."}
    )
    assert posted.status_code == 200

    assert queued.get("/review/queue").json()["items"] == []


@pytest.mark.integration
def test_approving_promotes_the_link(queued):
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    queued.post(f"/review/{source}/{target}", json={"verdict": "approve"})

    driver = queued.app.state.driver
    records, _, _ = driver.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=queued.app.state.settings.neo4j_database,
    )
    assert [(r["source"], r["target"]) for r in records] == [(source, target)]


@pytest.mark.integration
def test_rejecting_promotes_nothing(queued):
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    queued.post(f"/review/{source}/{target}", json={"verdict": "reject"})

    driver = queued.app.state.driver
    records, _, _ = driver.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total",
        database_=queued.app.state.settings.neo4j_database,
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_the_actor_is_the_authenticated_principal_not_the_request_body(queued):
    """A client-supplied actor would make the audit trail worthless — anyone
    could record a decision as anyone."""
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    queued.post(
        f"/review/{source}/{target}",
        json={"verdict": "approve", "rationale": "r", "actor": "somebody-else"},
    )

    driver = queued.app.state.driver
    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN d.actor AS actor",
        database_=queued.app.state.settings.neo4j_database,
    )
    assert records[0]["actor"] == "tester"


@pytest.mark.integration
def test_an_unknown_verdict_is_a_400(queued):
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    response = queued.post(f"/review/{source}/{target}", json={"verdict": "maybe"})
    assert response.status_code == 400
    assert "verdict" in response.json()["detail"]


@pytest.mark.integration
def test_deciding_a_pair_that_was_never_proposed_is_a_404(queued):
    """Otherwise an audit record accumulates about a link nothing ever suggested."""
    response = queued.post(
        "/review/not-an-obligation/nor-is-this", json={"verdict": "approve"}
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_both_review_routes_require_a_principal(client_with_graph):
    """This is the route that writes an audit record; it must never be anonymous."""
    assert client_with_graph.get("/review/queue").status_code == 401
    assert (
        client_with_graph.post("/review/a/b", json={"verdict": "approve"}).status_code
        == 401
    )


@pytest.mark.integration
def test_an_obligation_anchored_to_two_chunks_appears_once(client_with_auth):
    """Chunk overlap repeats a sentence across a section split, so one obligation
    can legitimately anchor to two chunks — measured at 5 of 88 on a real DoD
    issuance. The queue must still show it once: a reviewer handed the same pair
    twice does the work twice, and the second verdict has nothing left to decide.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    _seed_version(
        driver, database, version_id="higher", name="DoDI 5000.88", statement=HIGHER
    )
    driver.execute_query(
        "MERGE (d:Document {slug: 'org', name: 'ORG 1.0'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'org', "
        "checksum: 'org', source_uri: 'file:///x.pdf'})",
        database_=database,
    )
    body = " ".join(f"word{i}" for i in range(400))
    split = chunk_pages(
        [f"2.4. DUTIES.\n{body}"], version_id="org", max_chars=600, overlap_chars=150
    )
    assert len({c.chunk_id for c in split}) > 1
    assert len({tuple(c.section_path) for c in split}) == 1

    obligation = ExtractedObligation(
        statement=ORG,
        modality=Modality.MUST,
        actor=None,
        deadline=None,
        conditions=None,
        confidence=0.9,
    )
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id="org", chunks=split)
        # The same statement read out of two overlapping chunks: one obligation,
        # two ANCHORED_IN edges.
        for chunk in split[:2]:
            session.execute_write(
                write_obligations,
                version_id="org",
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[obligation],
            )
        session.execute_write(
            propose_links,
            org_version_id="org",
            candidate_version_ids=["higher"],
            proposer="lexical-v1",
        )

    records, _, _ = driver.execute_query(
        "MATCH (o:Obligation {statement: $statement})-[a:ANCHORED_IN]->() "
        "RETURN count(a) AS anchors",
        {"statement": ORG},
        database_=database,
    )
    assert records[0]["anchors"] == 2, "the fixture must actually double-anchor"

    queue = client_with_auth.get("/review/queue").json()["items"]
    assert len(queue) == 1


# --- why the queue is empty (STORY-090) ---------------------------------------

COMPARABLE = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)-[:MANDATES]->(:Obligation)
WITH d, count(DISTINCT v) AS editions_with_obligations
WHERE editions_with_obligations > 1
RETURN count(d) AS comparable
"""


@pytest.mark.integration
def test_the_queue_says_no_edition_holds_obligations(client_with_auth):
    """An empty queue has three causes and says which. This is the first: nothing
    has been extracted anywhere, so no proposal could exist."""
    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 0
    assert body["documents_comparable"] == 0


@pytest.mark.integration
def test_the_queue_says_one_side_is_missing(client_with_auth):
    """The second, and the state the live graph was in on 2026-08-26: obligations
    exist, but no document has two editions holding them, so a proposal has
    nothing to be made between."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(driver, database, version_id="only@2020", name="Only", statement=ORG)

    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 1
    assert body["documents_comparable"] == 0


@pytest.mark.integration
def test_the_queue_reports_a_document_whose_editions_can_be_compared(
    client_with_auth,
):
    """The third: both sides exist, so an empty queue really does mean the work
    has been done rather than that it could not start."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    # One document, two editions, each mandating something — the shape a proposal
    # needs. `_seed_version` keys a document per version, so this is built here.
    driver.execute_query(
        "MERGE (d:Document {slug: 'two-editions', name: 'Two Editions'}) "
        "MERGE (d)-[:HAS_VERSION]->(a:DocumentVersion {version_id: 'te@2018', "
        "  checksum: 'a', source_uri: 'file:///a.pdf'}) "
        "MERGE (d)-[:HAS_VERSION]->(b:DocumentVersion {version_id: 'te@2020', "
        "  checksum: 'b', source_uri: 'file:///b.pdf'}) "
        "MERGE (a)-[:MANDATES]->(:Obligation {obligation_id: 'o-a', "
        "  statement: $higher, modality: 'MUST', section_path: ['1']}) "
        "MERGE (b)-[:MANDATES]->(:Obligation {obligation_id: 'o-b', "
        "  statement: $org, modality: 'MUST', section_path: ['1']})",
        {"higher": HIGHER, "org": ORG},
        database_=database,
    )

    body = client_with_auth.get("/review/queue").json()

    assert body["editions_with_obligations"] == 2
    assert body["documents_comparable"] == 1
