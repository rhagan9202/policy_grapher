"""Reading the obligations an edition holds — STORY-081.

Obligations are the product's central noun: extraction produces them, Review
judges links between them, Triage ranks changes to them. Until this route they
were reachable in three places only — as a count in a rebuild report, two at a
time in the Review queue, and quoted inside a Triage row. A rebuild on
2026-08-25 wrote 113 of them and confirming that number took `cypher-shell`,
which is not a tool the audience ADR-008 describes has.
"""

import pytest

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.obligations import write_obligations

PAGES = [
    "SECTION 1: PURPOSE\n1.1. SCOPE.\nThis issuance applies to the Components.\n",
    "SECTION 2: RESPONSIBILITIES\n2.1. DUTIES.\nThe Director carries them out.\n",
]


def _seed(driver, database, *, slug="dodi-5000-88", version_id="v@2020-01-01"):
    """One edition, two chunks, three obligations — two sharing a chunk."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: 'DoDI 5000.88'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///x.pdf'})",
        {"slug": slug, "vid": version_id},
        database_=database,
    )
    chunks = chunk_pages(PAGES, version_id=version_id)
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=chunks)
        # The later chunk is written first, so a route that returned insertion
        # order would put it first and the ordering assertion would catch it.
        for chunk, statements in (
            (chunks[-1], ["The Director shall report annually."]),
            (
                chunks[0],
                [
                    "Components shall apply this issuance.",
                    "Components will record their compliance.",
                ],
            ),
        ):
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=Modality.SHALL,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                    for statement in statements
                ],
            )
    return slug, version_id, chunks


@pytest.mark.integration
def test_an_edition_reports_the_obligations_it_mandates(client_with_auth):
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    slug, version_id, _ = _seed(driver, database)

    body = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations"
    ).json()

    assert body["total"] == 3
    assert body["returned"] == 3
    assert body["truncated"] is False
    statements = {item["statement"] for item in body["obligations"]}
    assert "The Director shall report annually." in statements
    first = body["obligations"][0]
    assert set(first) == {
        "obligation_id",
        "statement",
        "modality",
        "section_path",
        "page",
    }
    assert first["modality"] == "SHALL"
    assert first["page"] >= 1
    assert first["section_path"]


@pytest.mark.integration
def test_obligations_follow_the_document_rather_than_insertion_order(
    client_with_auth,
):
    """AC7. The natural Cypher return order is insertion order, and the seed
    writes the later chunk's obligation first precisely so that a route relying
    on it fails here.

    Ordering is by the anchoring chunk's `ordinal` — the property that already
    exists and already follows the document — then by `obligation_id` to break
    ties, because two obligations read out of the same chunk have no order
    between them and an unstable one makes the list shuffle between requests.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    slug, version_id, chunks = _seed(driver, database)

    body = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations"
    ).json()

    sections = [tuple(item["section_path"]) for item in body["obligations"]]
    assert sections[0] == tuple(chunks[0].section_path)
    assert sections[-1] == tuple(chunks[-1].section_path)

    again = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations"
    ).json()
    assert [item["obligation_id"] for item in again["obligations"]] == [
        item["obligation_id"] for item in body["obligations"]
    ]


@pytest.mark.integration
def test_an_unknown_document_is_missing_rather_than_empty(client_with_auth):
    """AC2. An empty list would read as "built, and it found nothing", which is
    a different fact needing a different action."""
    response = client_with_auth.get(
        "/documents/no-such-doc/versions/v@2020-01-01/obligations"
    )

    assert response.status_code == 404
    # The route's own message, not FastAPI's "Not Found" for an unrouted path.
    # Asserting the status alone passes while the route does not exist at all,
    # which is the vacuous-test shape this project keeps finding.
    assert "no-such-doc" in response.json()["detail"]


@pytest.mark.integration
def test_an_unknown_edition_is_missing_rather_than_empty(client_with_auth):
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    slug, _, _ = _seed(driver, database)

    response = client_with_auth.get(
        f"/documents/{slug}/versions/v@1999-01-01/obligations"
    )

    assert response.status_code == 404
    assert "v@1999-01-01" in response.json()["detail"]


@pytest.mark.integration
def test_an_edition_with_nothing_extracted_is_empty_rather_than_missing(
    client_with_auth,
):
    """The distinction the whole story turns on: this edition exists and has
    text, and extraction found nothing in it — or was never run. That is a 200
    with an empty list, and it is not the same answer as a 404."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    driver.execute_query(
        "MERGE (d:Document {slug: 'bare', name: 'Bare'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'bare@2020-01-01', "
        "checksum: 'x', source_uri: 'file:///x.pdf'})",
        database_=database,
    )

    response = client_with_auth.get(
        "/documents/bare/versions/bare@2020-01-01/obligations"
    )

    assert response.status_code == 200
    assert response.json() == {
        "obligations": [],
        "total": 0,
        "returned": 0,
        "truncated": False,
    }


@pytest.mark.integration
def test_it_caps_what_it_returns_and_still_reports_the_true_total(
    client_with_auth,
):
    """AC4. The largest edition in `data/samples` is 204 chunks and can produce
    several hundred obligations. Same idiom as the graph view and the document
    table: cap, and say so."""
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    slug, version_id, _ = _seed(driver, database)

    body = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations?limit=2"
    ).json()

    assert body["total"] == 3
    assert body["returned"] == 2
    assert body["truncated"] is True
    assert len(body["obligations"]) == 2
