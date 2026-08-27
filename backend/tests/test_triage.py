"""Propagating a change to the policies that implement it."""

import pytest

from policy_grapher.changes.diff import diff_versions
from policy_grapher.changes.propagate import KIND_WEIGHT, MODALITY_WEIGHT, triage
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.obligations import write_obligations

HIGHER_OLD = "Components shall document the cybersecurity strategy."
HIGHER_NEW = "Components shall document the cybersecurity strategy annually."
OURS = "The Program Manager shall document the cybersecurity strategy in the plan."


def _seed_version(driver, database, *, version_id, doc_slug, doc_name, entries):
    driver.execute_query(
        "MERGE (d:Document {slug: $slug}) SET d.name = $name "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"slug": doc_slug, "name": doc_name, "vid": version_id},
        database_=database,
    )
    ids = {}
    with driver.session(database=database) as session:
        for section, statement, modality in entries:
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
                        modality=modality,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                ],
            )
            ids[statement] = _obligation_id(driver, database, version_id, statement)
    return ids


def _seed_two_editions_without_obligations(client):
    """Two editions of one instrument, superseding each other, neither carrying
    any obligations — what the default `null` extractor produces."""
    driver = client.app.state.driver
    database = client.app.state.settings.neo4j_database
    _seed_version(
        driver, database, version_id="d@2019-01-01", doc_slug="d",
        doc_name="Doc D", entries=[],
    )
    _seed_version(
        driver, database, version_id="d@2020-01-01", doc_slug="d",
        doc_name="Doc D", entries=[],
    )
    driver.execute_query(
        "MATCH (new:DocumentVersion {version_id: 'd@2020-01-01'}) "
        "MATCH (old:DocumentVersion {version_id: 'd@2019-01-01'}) "
        "MERGE (new)-[:SUPERSEDES]->(old)",
        database_=database,
    )


def _obligation_id(driver, database, version_id, statement):
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $vid})-[:MANDATES]->"
        "(o:Obligation {statement: $statement}) RETURN o.obligation_id AS id",
        {"vid": version_id, "statement": statement},
        database_=database,
    )
    return records[0]["id"]


def _link(driver, database, *, source, target, edge="IMPLEMENTS"):
    driver.execute_query(
        f"MATCH (a:Obligation {{obligation_id: $source}}) "
        f"MATCH (b:Obligation {{obligation_id: $target}}) "
        f"MERGE (a)-[:{edge}]->(b)",
        {"source": source, "target": target},
        database_=database,
    )


def _triage(driver, database, *, old="higher-v1", new="higher-v2"):
    with driver.session(database=database) as session:
        session.execute_write(
            diff_versions, from_version_id=old, to_version_id=new
        )
        return session.execute_write(
            triage, from_version_id=old, to_version_id=new
        )


@pytest.fixture
def changed_higher(clean_graph, database):
    """A higher-tier obligation reworded between two editions, and one of our
    clauses that implements it."""
    _seed_version(
        clean_graph, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    new_ids = _seed_version(
        clean_graph, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_NEW, Modality.SHALL)],
    )
    our_ids = _seed_version(
        clean_graph, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0", entries=[("2.4", OURS, Modality.SHALL)],
    )
    return {"higher_new": new_ids[HIGHER_NEW], "ours": our_ids[OURS]}


@pytest.mark.integration
def test_a_change_reaches_the_policy_that_implements_it(
    changed_higher, clean_graph, database
):
    _link(
        clean_graph, database,
        source=changed_higher["ours"], target=changed_higher["higher_new"],
    )

    result = _triage(clean_graph, database)

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.document == "ORG 1.0"
    assert row.our_statement == OURS
    assert row.our_section_path == ["2.4"]
    assert row.higher_statement == HIGHER_NEW
    assert row.previous_statement == HIGHER_OLD
    assert row.higher_section_path == ["3.2"]
    assert row.kind == "MODIFIED"
    assert row.score > 0


@pytest.mark.integration
def test_a_change_linked_only_by_a_proposal_produces_no_row(
    changed_higher, clean_graph, database
):
    """The invariant phase 4 exists to protect. A careless join here would put an
    unreviewed machine guess into a compliance answer."""
    _link(
        clean_graph, database,
        source=changed_higher["ours"], target=changed_higher["higher_new"],
        edge="IMPLEMENTS_PROPOSED",
    )

    result = _triage(clean_graph, database)

    assert result.rows == []
    assert result.unlinked_changes == 1


@pytest.mark.integration
def test_a_change_with_no_reviewed_link_is_counted_not_dropped(
    changed_higher, clean_graph, database
):
    """Silence is indistinguishable from 'nothing is affected'."""
    result = _triage(clean_graph, database)

    assert result.rows == []
    assert result.unlinked_changes == 1
    assert result.total_changes == 1


@pytest.mark.integration
def test_a_removed_obligation_we_implement_still_produces_a_row(
    clean_graph, database
):
    """Our policy now implements something that no longer exists. That is a live
    compliance gap and exactly what a reviewer needs to be told."""
    old_ids = _seed_version(
        clean_graph, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", HIGHER_OLD, Modality.SHALL), ("9.9", "We shall keep this.", Modality.SHALL)],
    )
    _seed_version(
        clean_graph, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("9.9", "We shall keep this.", Modality.SHALL)],
    )
    our_ids = _seed_version(
        clean_graph, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0", entries=[("2.4", OURS, Modality.SHALL)],
    )
    _link(clean_graph, database, source=our_ids[OURS], target=old_ids[HIGHER_OLD])

    result = _triage(clean_graph, database)

    assert len(result.rows) == 1
    assert result.rows[0].kind == "REMOVED"
    assert result.rows[0].higher_statement == HIGHER_OLD


@pytest.mark.integration
def test_a_changed_shall_outranks_a_changed_may(clean_graph, database):
    _seed_version(
        clean_graph, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", "Components shall do the binding thing.", Modality.SHALL),
                 ("3.3", "Components may do the optional thing.", Modality.MAY)],
    )
    new_ids = _seed_version(
        clean_graph, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", "Components shall do the binding thing now.", Modality.SHALL),
                 ("3.3", "Components may do the optional thing now.", Modality.MAY)],
    )
    our_ids = _seed_version(
        clean_graph, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0",
        entries=[("2.4", "We shall do the binding thing.", Modality.SHALL),
                 ("2.5", "We shall do the optional thing.", Modality.SHALL)],
    )
    _link(clean_graph, database, source=our_ids["We shall do the binding thing."],
          target=new_ids["Components shall do the binding thing now."])
    _link(clean_graph, database, source=our_ids["We shall do the optional thing."],
          target=new_ids["Components may do the optional thing now."])

    result = _triage(clean_graph, database)

    assert len(result.rows) == 2
    assert result.rows[0].modality == "SHALL"
    assert result.rows[1].modality == "MAY"
    assert result.rows[0].score > result.rows[1].score


@pytest.mark.integration
def test_a_removed_obligation_outranks_a_modified_one(clean_graph, database):
    """An org policy implementing something that no longer exists is a gap;
    a modified one is work."""
    old_ids = _seed_version(
        clean_graph, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", "Components shall keep records.", Modality.SHALL),
                 ("3.3", "Components shall destroy records.", Modality.SHALL)],
    )
    new_ids = _seed_version(
        clean_graph, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88",
        entries=[("3.2", "Components shall keep records forever.", Modality.SHALL)],
    )
    our_ids = _seed_version(
        clean_graph, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0",
        entries=[("2.4", "We shall keep records.", Modality.SHALL),
                 ("2.5", "We shall destroy records.", Modality.SHALL)],
    )
    _link(clean_graph, database, source=our_ids["We shall keep records."],
          target=new_ids["Components shall keep records forever."])
    _link(clean_graph, database, source=our_ids["We shall destroy records."],
          target=old_ids["Components shall destroy records."])

    result = _triage(clean_graph, database)

    assert [row.kind for row in result.rows] == ["REMOVED", "MODIFIED"]
    assert result.rows[0].score > result.rows[1].score


def test_the_weights_are_named_and_ordered():
    """A magic number buried in Cypher is a ranking nobody can argue with."""
    assert MODALITY_WEIGHT["SHALL"] == MODALITY_WEIGHT["MUST"]
    assert MODALITY_WEIGHT["SHALL"] > MODALITY_WEIGHT["SHOULD"] > MODALITY_WEIGHT["MAY"]
    assert KIND_WEIGHT["REMOVED"] > KIND_WEIGHT["MODIFIED"] > KIND_WEIGHT["ADDED"]


def test_every_modality_the_schema_allows_has_a_weight():
    """An unweighted modality would silently rank at whatever the fallback is."""
    assert set(MODALITY_WEIGHT) == {m.value for m in Modality}


# The table as decided, written out. STORY-085: the test above compares the
# table's *keys* against the enum and caught WILL's addition within a minute of
# it being made — which is exactly what sprint 5's retrospective praises it for.
# It says nothing about the values, so every ranking decision this project has
# taken lived in a comment and was enforced by nothing.
EXPECTED_MODALITY_WEIGHT = {
    "SHALL": 4.0,
    "MUST": 4.0,
    "WILL": 4.0,
    "SHOULD": 2.0,
    "MAY": 1.0,
}


def test_will_is_weighted_as_heavily_as_shall():
    """The ranking claim ADR-025 makes, asserted rather than commented.

    DoD's plain-language drafting replaced the directive `shall` with `will`, so
    the two impose the same duty. In this corpus `will` appears 458 times against
    `shall`'s 93 (ADR-025), which makes WILL the dominant binding modality — and
    means a single character here moves most of the corpus, not an edge case.

    Weighting WILL below SHALL would also rank a 2020 re-issue as less urgent
    than its 2003 edition purely because the drafting convention changed
    underneath it, which is the specific wrong answer ADR-025 exists to prevent.
    """
    assert MODALITY_WEIGHT["WILL"] == MODALITY_WEIGHT["SHALL"], (
        f"ADR-025 decided WILL is as binding as SHALL, but WILL weighs "
        f"{MODALITY_WEIGHT['WILL']} against SHALL's {MODALITY_WEIGHT['SHALL']}. "
        f"This corpus uses `will` 458 times to `shall`'s 93, so this sends its "
        f"dominant binding modality to the bottom of every Triage ranking."
    )


def test_the_modality_weights_are_exactly_what_was_decided():
    """An explicit mapping, so a changed value fails and names what changed.

    The ordering assertions above allow any values that keep the order, so
    halving every weight — or moving WILL to sit between SHOULD and SHALL —
    passes them all while re-ranking the corpus.
    """
    assert MODALITY_WEIGHT == EXPECTED_MODALITY_WEIGHT, (
        "the modality weights no longer match what ADR-025 decided; "
        + "; ".join(
            f"{modality} is {MODALITY_WEIGHT.get(modality)} not {expected}"
            for modality, expected in EXPECTED_MODALITY_WEIGHT.items()
            if MODALITY_WEIGHT.get(modality) != expected
        )
        + ". Ranking is what a reviewer sees first, so change the ADR before the table."
    )


@pytest.mark.integration
def test_an_obligation_anchored_to_two_chunks_produces_one_row(clean_graph, database):
    """Chunk overlap repeats a sentence across a section split, so an obligation
    can anchor to two chunks — 5 of 88 on a real DoD issuance. A row per
    combination would inflate the triage count and show the same clause twice,
    which is the same defect the review queue had."""
    _seed_version(
        clean_graph, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    new_ids = _seed_version(
        clean_graph, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_NEW, Modality.SHALL)],
    )
    our_ids = _seed_version(
        clean_graph, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0", entries=[("2.4", OURS, Modality.SHALL)],
    )
    _link(clean_graph, database, source=our_ids[OURS], target=new_ids[HIGHER_NEW])

    # A second chunk of the same section, anchoring the same obligation.
    body = " ".join(f"word{i}" for i in range(400))
    split = chunk_pages(
        [f"2.4. TITLE.\n{body}"], version_id="ours-v1", max_chars=600, overlap_chars=150
    )
    assert len(split) > 1
    with clean_graph.session(database=database) as session:
        # split[1], not split[0]: a chunk id is keyed on its position within the
        # section, so the first chunk of section 2.4 is the one already seeded.
        session.execute_write(write_chunks, version_id="ours-v1", chunks=split[1:2])
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) "
        "MATCH (c:Chunk {chunk_id: $chunk}) MERGE (o)-[:ANCHORED_IN]->(c)",
        {"id": our_ids[OURS], "chunk": split[1].chunk_id},
        database_=database,
    )
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Obligation {obligation_id: $id})-[a:ANCHORED_IN]->() "
        "RETURN count(a) AS anchors",
        {"id": our_ids[OURS]},
        database_=database,
    )
    assert records[0]["anchors"] == 2, "the fixture must actually double-anchor"

    result = _triage(clean_graph, database)

    assert len(result.rows) == 1


# --- the API ------------------------------------------------------------------


@pytest.fixture
def triage_client(client_with_auth):
    """Two editions of a higher-tier issuance, a reworded obligation, one of our
    clauses implementing it, and a SUPERSEDES chain between the editions."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    _seed_version(
        driver, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    new_ids = _seed_version(
        driver, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_NEW, Modality.SHALL)],
    )
    our_ids = _seed_version(
        driver, database, version_id="ours-v1", doc_slug="ours",
        doc_name="ORG 1.0", entries=[("2.4", OURS, Modality.SHALL)],
    )
    _link(driver, database, source=our_ids[OURS], target=new_ids[HIGHER_NEW])
    driver.execute_query(
        "MATCH (new:DocumentVersion {version_id: 'higher-v2'}) "
        "MATCH (old:DocumentVersion {version_id: 'higher-v1'}) "
        "MERGE (new)-[:SUPERSEDES]->(old)",
        database_=database,
    )
    return client_with_auth


@pytest.mark.integration
def test_the_route_answers_with_ranked_rows_and_both_citations(triage_client):
    """Nothing in the response is unsourced."""
    response = triage_client.get(
        "/triage", params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["from_version_id"] == "higher-v1"
    assert body["to_version_id"] == "higher-v2"
    assert body["total_changes"] == 1
    assert body["unlinked_changes"] == 0

    row = body["rows"][0]
    assert row["kind"] == "MODIFIED"
    assert row["previous_statement"] == HIGHER_OLD
    assert row["ours"] == {
        "obligation_id": row["ours"]["obligation_id"],
        "statement": OURS,
        "document": "ORG 1.0",
        "section_path": ["2.4"],
        "page": 1,
    }
    assert row["higher"]["document"] == "DoDI 5000.88"
    assert row["higher"]["statement"] == HIGHER_NEW
    assert row["higher"]["section_path"] == ["3.2"]


@pytest.mark.integration
def test_omitting_the_earlier_edition_uses_the_one_it_supersedes(triage_client):
    """And the response says which, so a caller who did not choose still knows
    what the answer is about."""
    response = triage_client.get("/triage", params={"to_version_id": "higher-v2"})

    assert response.status_code == 200
    assert response.json()["from_version_id"] == "higher-v1"
    assert len(response.json()["rows"]) == 1


@pytest.mark.integration
def test_an_unknown_edition_is_a_404_not_an_empty_answer(triage_client):
    """An empty result reads as 'nothing is affected'. A mistyped version id must
    never be able to produce that."""
    response = triage_client.get("/triage", params={"to_version_id": "no-such-edition"})
    assert response.status_code == 404

    response = triage_client.get(
        "/triage",
        params={"to_version_id": "higher-v2", "from_version_id": "no-such-edition"},
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_an_edition_with_no_predecessor_is_refused_rather_than_answered(triage_client):
    """'higher-v1' is the oldest edition. Comparing it against nothing would
    report every obligation in it as newly added."""
    response = triage_client.get("/triage", params={"to_version_id": "higher-v1"})

    assert response.status_code == 400
    assert "supersedes no earlier edition" in response.json()["detail"]


@pytest.mark.integration
def test_the_route_requires_a_principal(client_with_graph):
    response = client_with_graph.get(
        "/triage", params={"to_version_id": "higher-v2"}
    )
    assert response.status_code == 401


@pytest.mark.integration
def test_an_empty_triage_still_reports_what_it_could_not_see(client_with_auth):
    """The false-all-clear guard, at the API boundary."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    _seed_version(
        driver, database, version_id="higher-v1", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    _seed_version(
        driver, database, version_id="higher-v2", doc_slug="higher",
        doc_name="DoDI 5000.88", entries=[("3.2", HIGHER_NEW, Modality.SHALL)],
    )

    body = client_with_auth.get(
        "/triage", params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"}
    ).json()

    assert body["rows"] == []
    assert body["total_changes"] == 1
    assert body["unlinked_changes"] == 1


@pytest.mark.integration
def test_triage_reports_how_many_obligations_each_edition_has(client_with_auth):
    """"No obligation changed between these editions" is true and misleading
    when neither edition has any obligations to change — which is what the
    default null extractor produces. This is the same discipline
    `unlinked_changes` already applies to an empty table (ADR-015).

    Two pairs, in one graph, on purpose. Asserting only that an empty pair
    reports zero proves nothing about where the number came from: a route
    returning a hardcoded `0` passes that assertion exactly as well as one
    reading the graph. So a second pair carries obligations, and carries a
    different number on each side — one before, two after — which no constant
    and no single shared read can satisfy.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database

    _seed_two_editions_without_obligations(client_with_auth)
    _seed_version(
        driver, database, version_id="e@2019-01-01", doc_slug="e",
        doc_name="Doc E", entries=[("3.2", HIGHER_OLD, Modality.SHALL)],
    )
    _seed_version(
        driver, database, version_id="e@2020-01-01", doc_slug="e",
        doc_name="Doc E",
        entries=[("3.2", HIGHER_NEW, Modality.SHALL),
                 ("3.3", "Components shall log every access.", Modality.SHALL)],
    )
    driver.execute_query(
        "MATCH (new:DocumentVersion {version_id: 'e@2020-01-01'}) "
        "MATCH (old:DocumentVersion {version_id: 'e@2019-01-01'}) "
        "MERGE (new)-[:SUPERSEDES]->(old)",
        database_=database,
    )

    empty = client_with_auth.get(
        "/triage", params={"to_version_id": "d@2020-01-01"}
    ).json()

    assert empty["total_changes"] == 0
    assert empty["from_obligations"] == 0
    assert empty["to_obligations"] == 0

    filled = client_with_auth.get(
        "/triage", params={"to_version_id": "e@2020-01-01"}
    ).json()

    assert filled["from_obligations"] == 1
    assert filled["to_obligations"] == 2


@pytest.mark.integration
def test_repeating_the_request_does_not_accumulate_changes(triage_client):
    """The diff runs on a GET. It drops and rewrites its own version pair, so
    repeating converges rather than piling up."""
    first = triage_client.get(
        "/triage", params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"}
    ).json()
    second = triage_client.get(
        "/triage", params={"to_version_id": "higher-v2", "from_version_id": "higher-v1"}
    ).json()

    assert first == second
    records, _, _ = triage_client.app.state.driver.execute_query(
        "MATCH (c:Change) RETURN count(c) AS total",
        database_=triage_client.app.state.settings.neo4j_database,
    )
    assert records[0]["total"] == 1
