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
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.obligations import write_obligations

CATEGORIES = {
    "documents",
    "versions",
    "chunks",
    "obligations",
    "proposals",
    "decisions",
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
    reviewer's verdict is not, and Reset deletes the only copy."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    driver.execute_query(
        "CREATE (:LinkDecision {decision_key: 'k1', source_obligation_id: 'a', "
        "target_obligation_id: 'b', verdict: 'approve', actor: 'reviewer', "
        "decided_at: '2026-08-25T00:00:00+00:00'})",
        database_=database,
    )

    body = client_with_auth.get("/export").json()

    assert len(body["decisions"]) == 1
    decision = body["decisions"][0]
    assert decision["decision_key"] == "k1"
    assert decision["verdict"] == "approve"
    assert decision["source_obligation_id"] == "a"
    assert decision["target_obligation_id"] == "b"
