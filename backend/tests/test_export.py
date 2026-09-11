"""Taking a copy before Reset destroys it — STORY-083.

The Reset screen said it itself: "There is no undo and no export." What it
destroys is not cheap — the 37-chunk rebuild on 2026-08-25 cost hours of CPU
inference — but extraction is cached and therefore repeatable (ADR-013). Review
decisions are not. A human's judgment about whether one clause implements
another is the only thing in this system a machine cannot regenerate, and the
confirm dialog already says a rebuild replays them and cannot bring them back.
"""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.decisions import decision_key, record_decision
from policy_grapher.links.pairing import pairing_key, record_pairing
from policy_grapher.migrate import migrate_pairing_decisions
from policy_grapher.obligations import write_obligations

CATEGORIES = {
    "documents",
    "versions",
    "chunks",
    "obligations",
    "proposals",
    "decisions",
    "pairing_decisions",
    "changes",
}


@pytest.mark.integration
def test_an_empty_graph_exports_a_well_formed_document(client_with_auth):
    """AC6. An empty corpus is a legitimate state — ADR-019 makes it the first
    thing a new user sees — so exporting one must not fail."""
    body = client_with_auth.get("/export").json()

    assert set(body) >= CATEGORIES
    for category in CATEGORIES:
        assert body[category] == [], category


@pytest.mark.integration
def test_the_export_names_its_categories_at_the_top_level(client_with_auth):
    """AC5, replacing an acceptance criterion that read "its structure is
    obvious", which no test could fail. A reader finds a category by name
    without consulting the code that wrote the file."""
    body = client_with_auth.get("/export").json()

    assert set(body) >= CATEGORIES
    assert all(isinstance(body[category], list) for category in CATEGORIES)


@pytest.mark.integration
def test_the_export_carries_what_reset_destroys(client_with_auth):
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    version_id = "dodi-5000-88@2020-01-01"
    driver.execute_query(
        "MERGE (d:Document {slug: 'dodi-5000-88', name: 'DoDI 5000.88'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        {"vid": version_id},
        database_=database,
    )
    chunks = chunk_pages(
        ["SECTION 1: PURPOSE\n1.1. SCOPE.\nComponents shall comply.\n"],
        version_id=version_id,
    )
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=chunks)
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunks[0].chunk_id,
            section_path=chunks[0].section_path,
            obligations=[
                ExtractedObligation(
                    statement="Components shall comply.",
                    modality=Modality.SHALL,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
            ],
        )

    body = client_with_auth.get("/export").json()

    assert [d["slug"] for d in body["documents"]] == ["dodi-5000-88"]
    assert [v["version_id"] for v in body["versions"]] == [version_id]
    assert body["chunks"] and body["obligations"]

    # AC3: every record carries the identifier the graph keys on, so the file
    # can be joined back together and a future import has something stable to
    # match on.
    assert all("chunk_id" in chunk for chunk in body["chunks"])
    assert all("version_id" in chunk for chunk in body["chunks"])
    assert all("obligation_id" in o for o in body["obligations"])
    assert all("version_id" in o for o in body["obligations"])


@pytest.mark.integration
def test_the_export_carries_the_decisions_a_rebuild_cannot_regenerate(
    client_with_auth,
):
    """The thing worth exporting. Extraction is cached and repeatable; a
    reviewer's verdict is not, and Reset deletes the only copy.

    The decision is recorded through `record_decision`, not CREATEd with
    literal properties. The first version of this test wrote a node carrying
    the export query's own column names and asserted them back — which passed
    while every verdict recorded through the real path exported with a null
    key, a null timestamp, and no rationale."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    with driver.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id="a",
            target_id="b",
            verdict="approve",
            actor="reviewer",
            rationale="the org clause names the same duty",
        )

    body = client_with_auth.get("/export").json()

    assert len(body["decisions"]) == 1
    decision = body["decisions"][0]
    assert decision["key"] == decision_key("a", "b")
    assert decision["verdict"] == "approve"
    assert decision["actor"] == "reviewer"
    assert decision["rationale"] == "the org clause names the same duty"
    assert decision["at"], "the timestamp record_decision writes must survive export"
    assert decision["source_obligation_id"] == "a"
    assert decision["target_obligation_id"] == "b"


@pytest.mark.integration
def test_the_export_carries_a_retired_decision_and_the_reason_it_was_retired(
    client_with_auth,
):
    """The startup migration takes same-document decisions out of
    `:LinkDecision` — that is how it stops `PROMOTE` resurrecting their edges —
    and this query matched that label alone. So the first boot after the
    pairing split moved every legacy verdict out of the only copy the product
    offers, while `/admin/reset` went on deleting everything and the Reset
    screen went on calling the export the user's only copy.

    Measured before the fix: one decision exported, then zero once the
    migration had run, with nothing in between saying so. Retirement is not
    deletion — ADR-014 turns on the verdict surviving — and a verdict that
    survives only where no export can reach it survives on paper.

    `retired_reason` comes with it because the verdict alone no longer explains
    itself: a reader has to know whether a person's judgement was converted,
    refused as ambiguous, or left for them to settle by hand."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    version_id = "dodd-5000-01@2018-08-31"
    driver.execute_query(
        "MERGE (d:Document {slug: 'dodd-5000-01', name: 'DoDD 5000.01'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        {"vid": version_id},
        database_=database,
    )
    statements = [
        "The Director shall notify the Comptroller.",
        "Components shall file the annual report.",
    ]
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[
                ExtractedObligation(
                    statement=s,
                    modality=Modality.SHALL,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
                for s in statements
            ],
        )
    first, second = (
        obligation_id(version_id, chunk.section_path, s) for s in statements
    )
    # Raw, because `record_decision` now refuses a pair inside one document.
    # That refusal is why this state can only be an inheritance from before the
    # split, and why the migration exists to retire it.
    driver.execute_query(
        "MERGE (d:LinkDecision {key: $key}) "
        "SET d.source_obligation_id = $source, d.target_obligation_id = $target, "
        "    d.verdict = 'approve', d.actor = 'reviewer', "
        "    d.rationale = 'recorded before the split', d.at = datetime()",
        {"key": decision_key(first, second), "source": first, "target": second},
        database_=database,
    )
    counts = migrate_pairing_decisions(driver, database)
    assert counts["retired_same_edition"] == 1

    body = client_with_auth.get("/export").json()

    assert len(body["decisions"]) == 1, (
        "a retired decision is still a human verdict Reset would destroy"
    )
    decision = body["decisions"][0]
    assert decision["retired_reason"] == "same_edition"
    assert decision["key"] == decision_key(first, second)
    assert decision["verdict"] == "approve"
    assert decision["actor"] == "reviewer"
    assert decision["rationale"] == "recorded before the split"
    assert decision["at"], "the timestamp must survive retirement and export alike"
    assert decision["source_obligation_id"] == first
    assert decision["target_obligation_id"] == second


@pytest.mark.integration
def test_the_export_carries_pairing_decisions_under_their_own_category(
    client_with_auth,
):
    """The second canonical node. `:PairingDecision` answers the other question
    in the other vocabulary, and Reset deletes it exactly as hard.

    Recorded through `record_pairing`, not CREATEd with this query's own column
    names — the mistake the `:LinkDecision` category was repaired for, where a
    test asserted back the literals its own fixture had written while every
    verdict recorded through the real path exported empty.

    Its own category rather than a row in `decisions`: the properties are
    `old`/`new`, not `source`/`target`, and flattening the two would lose which
    question a verdict answered."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    with driver.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id="old-clause",
            new_id="new-clause",
            verdict="paired",
            actor="reviewer",
            rationale="the same duty, reworded",
        )

    body = client_with_auth.get("/export").json()

    assert len(body["pairing_decisions"]) == 1
    pairing = body["pairing_decisions"][0]
    assert pairing["key"] == pairing_key("old-clause", "new-clause")
    assert pairing["old_obligation_id"] == "old-clause"
    assert pairing["new_obligation_id"] == "new-clause"
    assert pairing["verdict"] == "paired"
    assert pairing["actor"] == "reviewer"
    assert pairing["rationale"] == "the same duty, reworded"
    assert pairing["at"], "the timestamp record_pairing writes must survive export"
