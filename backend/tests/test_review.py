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

    item = response.json()[0]
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
    item = queued.get("/review/queue").json()[0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    posted = queued.post(
        f"/review/{source}/{target}", json={"verdict": "approve", "rationale": "Yes."}
    )
    assert posted.status_code == 200

    assert queued.get("/review/queue").json() == []


@pytest.mark.integration
def test_approving_promotes_the_link(queued):
    item = queued.get("/review/queue").json()[0]
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
    item = queued.get("/review/queue").json()[0]
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
    item = queued.get("/review/queue").json()[0]
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
    item = queued.get("/review/queue").json()[0]
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
