"""Reading the obligations an edition holds — STORY-081.

Obligations are the product's central noun: extraction produces them, Review
judges links between them, Triage ranks changes to them. Until this route they
were reachable in three places only — as a count in a rebuild report, two at a
time in the Review queue, and quoted inside a Triage row. A rebuild on
2026-08-25 wrote 113 of them and confirming that number took `cypher-shell`,
which is not a tool the audience ADR-008 describes has.
"""

import pytest
from support import STAMP

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
        session.execute_write(write_chunks, version_id=version_id, chunks=chunks, pipeline_stamp=STAMP)
        # The later chunk is written first, so a route that returned insertion
        # order would put it first and the ordering assertion would catch it.
        for chunk, statements in (
            (chunks[-1], ["The Director shall report annually."]),
            (
                chunks[0],
                [
                    "Components shall apply this issuance.",
                    "Components shall record their compliance.",
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


# Found on 2026-09-08, driving the containerised stack against a graph that had
# been rebuilt with a real extractor. The screen said, of one edition:
#
#     62 obligations. Showing the first 0.
#
# `COUNT_OBLIGATIONS` matches `(:DocumentVersion)-[:MANDATES]->(:Obligation)` and
# saw 62. `LIST_OBLIGATIONS` additionally binds each obligation's anchoring chunk
# through `primary_anchor`, whose `CALL` subquery is an inner join — an
# obligation with no `:ANCHORED_IN` chunk contributes no row, so it returned
# none. Both queries are correct about what they ask; the graph underneath them
# was not.
#
# The cause is `_write_document`'s `drop_chunks` (ingest.py). It is a
# `DETACH DELETE`, so it removes each chunk *and every relationship touching it*
# — including the `:ANCHORED_IN` edges obligations use to cite a passage. The
# obligations themselves hang off the version by `:MANDATES` and survive the
# drop, unanchored and unreadable: they cannot be listed, cited, quoted in a
# Triage row, or shown either side of a Review proposal. `drop_chunks`'s comment
# reasons carefully about not orphaning *chunks* and does not consider what
# anchors into them.
#
# The counts stay wrong in the reader's favour, which is the dangerous
# direction: Triage went on reporting `from_obligations: 83, to_obligations: 62`
# and ranking 133 changes over clauses no screen could ever display.
@pytest.mark.integration
def test_reingesting_a_pdf_does_not_orphan_the_obligations_of_its_edition(
    client_with_auth, driver, database, monkeypatch
):
    """A re-ingest that rewrites replaces an edition's chunks. It must not leave
    that edition's obligations anchored to chunks that no longer exist.

    Re-ingesting is routine and additive by design (ADR-007) — the same file
    scanned again, a chunker improvement, a second edition arriving — so this is
    not an exotic path. What makes it silent is that nothing fails: ingest
    answers 200, the obligation count is unchanged, and only a screen that asks
    for the obligations themselves discovers there are none to be had.
    """
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    assert first.status_code == 200, first.text
    slug = first.json()["document"]["slug"]
    version_id = first.json()["version_id"]

    chunks = client_with_auth.get(f"/documents/{slug}/chunks").json()
    assert chunks, "the fixture PDF must produce at least one chunk"
    anchor = chunks[0]

    with driver.session(database=database) as session:
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=anchor["chunk_id"],
            section_path=anchor["section_path"],
            obligations=[
                ExtractedObligation(
                    statement="The program manager shall conduct assessments.",
                    modality=Modality.SHALL,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
            ],
        )

    before = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations"
    ).json()
    assert before["total"] == 1
    assert before["returned"] == 1, "precondition: the obligation is readable"

    # A re-ingest that actually rewrites. Re-posting the identical file is now
    # the skip case (ADR-042), which discards nothing and would satisfy every
    # assertion below without running a line of the code this test guards — the
    # same hazard the two sibling tests in this file and in test_chunks.py were
    # rescoped for.
    from policy_grapher import ingest as ingest_module

    monkeypatch.setattr(
        ingest_module, "pipeline_stamp", lambda: "a-different-pipeline"
    )
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    after = client_with_auth.get(
        f"/documents/{slug}/versions/{version_id}/obligations"
    ).json()

    # Whatever the chosen repair — re-anchor, drop the obligations with the
    # chunks, or refuse the re-ingest — `total` and `returned` must agree. An
    # edition reporting obligations it cannot produce is the contradiction
    # ADR-019 forbids, wearing the derived layer's clothes.
    assert after["returned"] == after["total"], (
        f"edition reports {after['total']} obligations but can list "
        f"{after['returned']} — re-ingest orphaned them from their chunks"
    )


@pytest.mark.integration
def test_a_reingest_that_rewrites_returns_its_edition_to_never_built(
    client_with_auth, driver, database, monkeypatch
):
    """Dropping the derived layer without clearing the build record swaps one
    contradiction for another.

    STORY-082 records the current or last build on the edition so that an
    edition holding zero obligations can say *why*. If a re-ingest throws the
    obligations away and leaves that record standing, the detail screen reads
    "Built 2026-08-30 with extractor local" directly above "No obligations
    recorded for this edition" — a build whose output no longer exists,
    described in the past tense as though it did.

    `build_state IS NULL` is already the encoding for never-built, and after a
    re-ingest that discards the derived layer that is what the edition is:
    freshly chunked text with nothing extracted from it.

    Scoped to a re-ingest that actually rewrites. Since ADR-042 an unchanged
    one discards nothing and the build record must *stand* — the opposite
    assertion, covered by
    `test_an_unchanged_re_ingest_keeps_the_derived_layer_and_its_verdicts` in
    test_ingest.py. The two are the same rule read from either side: the record
    describes the derived layer, so it survives exactly when that layer does.
    """
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = first.json()["document"]["slug"]
    version_id = first.json()["version_id"]

    driver.execute_query(
        "MATCH (v:DocumentVersion {version_id: $vid}) "
        "SET v.build_state = 'finished', v.build_run_id = 'run-9', "
        "    v.build_extractor_adapter = 'local', v.build_counts = '{}'",
        {"vid": version_id},
        database_=database,
    )
    before = client_with_auth.get(f"/documents/{slug}/versions").json()
    seeded = next(v for v in before if v["version_id"] == version_id)
    assert seeded["build_state"] == "finished", (
        "precondition: the edition claims a finished build"
    )

    # A different pipeline, so this re-ingest is one that rewrites: the edition
    # is no longer current, the derived layer goes, and the record describing it
    # must go with it.
    from policy_grapher import ingest as ingest_module

    monkeypatch.setattr(ingest_module, "pipeline_stamp", lambda: "a-different-pipeline")
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    after = client_with_auth.get(f"/documents/{slug}/versions").json()
    edition = next(v for v in after if v["version_id"] == version_id)
    assert edition["build_state"] is None, (
        "a re-ingest threw away what that build produced, so the edition must "
        f"not still report build_state={edition['build_state']!r}"
    )
    assert edition["build_extractor_adapter"] is None
