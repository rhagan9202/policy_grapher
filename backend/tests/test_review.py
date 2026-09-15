"""The review queue: what a human sees, and what their verdict is recorded as."""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.propose import propose_links
from policy_grapher.models import ReviewQueueOut
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


# --- why the queue is empty (STORY-090, redefined by the pairing design) -------


@pytest.mark.integration
def test_the_queue_says_no_edition_holds_obligations(client_with_auth):
    """An empty queue has three causes and says which. This is the first:
    nothing has been extracted anywhere, so no proposal could exist."""
    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 0
    assert body["documents_with_obligations"] == 0


@pytest.mark.integration
def test_the_queue_says_only_one_document_holds_obligations(client_with_auth):
    """The second: obligations exist, but in one document only. A proposal now
    runs between two documents — `propose_links` skips same-document pairs —
    so this configuration cannot fill the queue and the count must say so."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(driver, database, version_id="only@2020", name="Only", statement=ORG)

    body = client_with_auth.get("/review/queue").json()

    assert body["items"] == []
    assert body["editions_with_obligations"] == 1
    assert body["documents_with_obligations"] == 1


@pytest.mark.integration
def test_a_document_with_two_obligation_holding_editions_still_counts_once(
    client_with_auth,
):
    """The retired `documents_comparable` called exactly this shape comparable
    and reported the all-clear on it. It is now the configuration that can no
    longer yield a proposal, so it must read as one document — anything else is
    the false all-clear STORY-090 added this count to prevent."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    # One document, two editions, each mandating something. `_seed_version`
    # keys a document per version, so this is built here.
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
    assert body["documents_with_obligations"] == 1


@pytest.mark.integration
def test_the_queue_reports_two_documents_that_could_be_linked(client_with_auth):
    """Two documents each hold an obligation somewhere. That is necessary for a
    proposal, not sufficient: until someone rebuilds with candidates named,
    `proposals` stays 0 and the empty queue is "not yet proposed", not "caught
    up". One edition each — under the retired definition this read 0."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(
        driver, database, version_id="higher", name="DoDI 5000.88", statement=HIGHER
    )
    _seed_version(driver, database, version_id="org", name="ORG 1.0", statement=ORG)

    body = client_with_auth.get("/review/queue").json()

    assert body["editions_with_obligations"] == 2
    assert body["documents_with_obligations"] == 2
    assert body["proposals"] == 0
    assert body["pending"] == 0


@pytest.mark.integration
def test_the_queue_counts_proposals_even_when_none_are_pending(client_with_auth, queued):
    """`proposals` stays after a verdict so "caught up" is distinguishable from
    "never proposed". The fixture writes one undecided proposal; deciding it
    leaves the edge and zeros `pending`."""
    before = client_with_auth.get("/review/queue").json()
    assert before["proposals"] == 1
    assert before["pending"] == 1

    item = before["items"][0]
    client_with_auth.post(
        f"/review/{item['source']['obligation_id']}/{item['target']['obligation_id']}",
        json={"verdict": "approve"},
    )

    after = client_with_auth.get("/review/queue").json()
    assert after["proposals"] == 1
    assert after["pending"] == 0
    assert after["items"] == []


def test_the_review_queue_payload_carries_exactly_these_fields():
    """Not a test of the field names. A test that renaming one is deliberate.

    `frontend/src/api/types.ts` declares `ReviewQueue` by hand, and nothing
    checks the two declarations against each other. The dangerous direction was
    measured on this branch: with this payload renamed and the frontend left at
    its previous revision, `npm test` is fully green — eslint, `tsc -b`, all
    232 tests — while the screen reads a field that no longer arrives, gets
    `undefined`, falls through `undefined === 0`, and prints "Nothing is
    waiting for review." over a corpus where no proposal is possible. That is
    the false all-clear STORY-090 exists to prevent, delivered from behind a
    green gate. TypeScript catches only the opposite direction, where a stale
    screen meets a renamed `types.ts` and `tsc` fails with TS2339.

    Every other test in this file reads the payload by key and so pins the
    names too, but each does it while asking about something else and none of
    them says where the other half of the mirror lives. Changing this set is
    fine; changing it without opening `types.ts` is the defect.
    """
    assert set(ReviewQueueOut.model_fields) == {
        "items",
        "editions_with_obligations",
        "documents_with_obligations",
        "proposals",
        "pending",
    }


@pytest.mark.integration
def test_each_side_names_the_edition_it_came_from(queued):
    """Found in the sprint-12 review walkthrough, on a live queue of 119 pairs.

    Every proposal in it ran between two editions of *one* instrument —
    `dodd-5000-01@2022-07-28` against `dodd-5000-01@2018-08-31` — and both sides
    of the screen read `DoDD 5000.01`, because the citation carried the document
    and not the edition. The reviewer was asked whether one clause implements
    another and could not tell which of the two was which.

    `Citation`, on `/ask`, has carried `version_id` for exactly this reason: a
    corpus holding two editions of one directive answers out of both, so a
    citation naming only the document matches a passage in each of them and
    settles nothing. That reasoning is stronger here, not weaker — comparing
    editions is the whole of what this screen does.
    """
    item = queued.get("/review/queue").json()["items"][0]

    assert item["source"]["version_id"] == "org"
    assert item["target"]["version_id"] == "higher"


@pytest.mark.integration
def test_the_queue_says_how_many_proposals_are_waiting(queued):
    """The queue is capped at 50 and the response said nothing about the rest,
    so the screen read "Proposal 1 of 50" over 119 undecided pairs — and went on
    reading it after every verdict, because deciding one only refilled the page
    from the remainder. A reviewer had no measure of the work and no signal of
    progress.

    `pending` counts undecided proposals in the graph, not rows returned, so it
    falls as verdicts are recorded even while the page stays full. Counted on the
    server for the reason `ReviewQueueOut` already gives about its other counts:
    two views deriving the same number separately is how they come to disagree.
    """
    body = queued.get("/review/queue").json()

    assert body["pending"] == 1

    item = body["items"][0]
    queued.post(
        f"/review/{item['source']['obligation_id']}/{item['target']['obligation_id']}",
        json={"verdict": "approve"},
    )

    assert queued.get("/review/queue").json()["pending"] == 0


@pytest.mark.integration
def test_pending_counts_what_is_undecided_not_what_fits_on_the_page(client_with_auth):
    """The number that matters is the backlog, and `limit` must not change it —
    that *is* the original defect, stated exactly: the screen was reading a page
    size and calling it a total.

    Two proposals and a limit of one, so `pending` and `len(items)` cannot agree
    by accident. With a single-proposal fixture every assertion here would hold
    just as well if `pending` were `len(items)`, which would make this test agree
    with the bug it exists to catch.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    _seed_version(
        driver, database, version_id="higher", name="DoDI 5000.88", statement=HIGHER
    )
    _seed_version(
        driver, database, version_id="higher-2", name="DoDI 5000.89", statement=HIGHER
    )
    _seed_version(driver, database, version_id="org", name="ORG 1.0", statement=ORG)
    with driver.session(database=database) as session:
        assert (
            session.execute_write(
                propose_links,
                org_version_id="org",
                candidate_version_ids=["higher", "higher-2"],
                proposer="lexical-v1",
            )
            == 2
        )

    body = client_with_auth.get("/review/queue?limit=1").json()

    assert len(body["items"]) == 1
    assert body["pending"] == 2


def _seed_edition_of(driver, database, *, slug, version_id, statement):
    """One edition of a named document — unlike `_seed_version`, which mints a
    document per version and so can never build the same-document shape."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": slug, "vid": version_id},
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
    return obligation_id(version_id, chunk.section_path, statement)


@pytest.mark.integration
def test_a_same_document_verdict_is_a_400(client_with_auth):
    """`IMPLEMENTS` is cross-document only. `propose_links` no longer creates a
    same-document proposal and the startup migration deletes the legacy ones,
    but the graph this route meets is whatever it is — the guard in
    `record_decision` is the enforcement, and the route must translate its
    refusal into a 400 rather than 500 on it."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    older = _seed_edition_of(
        driver, database, slug="doc", version_id="doc@2018", statement=ORG
    )
    newer = _seed_edition_of(
        driver, database, slug="doc", version_id="doc@2022", statement=HIGHER
    )
    # Raw on purpose: this edge can only exist as an inheritance from before
    # the split, which is exactly the state the guard exists to meet.
    driver.execute_query(
        "MATCH (a:Obligation {obligation_id: $a}), (b:Obligation {obligation_id: $b}) "
        "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
        "proposer: 'lexical-v1'}]->(b)",
        {"a": newer, "b": older},
        database_=database,
    )

    response = client_with_auth.post(
        f"/review/{newer}/{older}", json={"verdict": "approve", "rationale": "r"}
    )

    assert response.status_code == 400
    assert "pairing" in response.json()["detail"]
    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0, "a refused verdict must leave no audit record"


@pytest.mark.integration
def test_a_fault_inside_the_write_is_not_reported_as_a_same_document_refusal(
    queued, monkeypatch
):
    """400 here means one thing: "your pair is a pairing question, take it to the
    pairings screen". Any other failure inside the write transaction is ours, and
    answering it with that status and that wording tells a reviewer something
    false about their data — these two clauses share a document — and sends them
    somewhere that cannot help.

    `ValueError` is not this module's private signal, which is the whole reason
    the refusal is a type. The driver raises a bare one out of `execute_write`
    when a parameter cannot be packed; that it cannot happen today rests on all
    five parameters being `str`, not on anything structural. Faked here rather
    than provoked, because the route's parameters all arrive through path and
    body validation and none of them can be made unpackable from outside.
    """
    item = queued.get("/review/queue").json()["items"][0]
    source, target = item["source"]["obligation_id"], item["target"]["obligation_id"]

    def _unpackable(tx):
        raise ValueError("Parameters of type object are not supported")

    monkeypatch.setattr(
        "policy_grapher.routers.review.replay_decisions", _unpackable
    )

    # Propagates as a server fault. TestClient re-raises rather than returning
    # 500, so the raise *is* the assertion that no 400 was manufactured.
    with pytest.raises(ValueError, match="not supported"):
        queued.post(
            f"/review/{source}/{target}",
            json={"verdict": "approve", "rationale": "r"},
        )
