from datetime import date

import pytest

from policy_grapher.versions import (
    UnknownDocumentError,
    VersionConflictError,
    attach_authority,
    link_supersession,
    merge_authority,
    merge_entity,
    merge_version,
    version_id,
)


def test_identity_prefers_the_effective_date():
    assert version_id("dodi-5000-88", date(2026, 4, 1), "abc123def456") == "dodi-5000-88@2026-04-01"


def test_identity_falls_back_to_a_checksum_prefix_when_undated():
    assert version_id("dodi-5000-88", None, "abc123def456789") == "dodi-5000-88@abc123def456"


def test_identity_is_stable_for_the_same_inputs():
    """Re-ingesting the same file must resolve to the same version, not a new one."""
    first = version_id("d", None, "abc123def456789")
    second = version_id("d", None, "abc123def456789")
    assert first == second


def test_two_editions_of_one_instrument_get_different_identities():
    a = version_id("d", date(2024, 1, 1), "aaa")
    b = version_id("d", date(2026, 1, 1), "bbb")
    assert a != b


@pytest.mark.integration
def test_a_version_attaches_to_its_document(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )

    with clean_graph.session(database=database) as session:
        resolved = session.execute_write(
            merge_version,
            document_slug="d",
            effective_date=date(2026, 4, 1),
            checksum="abc",
            source_uri="file:///d.pdf",
        )

    assert resolved == "d@2026-04-01"
    records, _, _ = clean_graph.execute_query(
        "MATCH (:Document {slug: 'd'})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        database_=database,
    )
    assert [r["id"] for r in records] == ["d@2026-04-01"]


@pytest.mark.integration
def test_re_merging_the_same_version_creates_nothing(clean_graph, database):
    """The DI-1 idempotency invariant, extended to versions."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    kwargs = {
        "document_slug": "d",
        "effective_date": None,
        "checksum": "abc",
        "source_uri": "file:///d.pdf",
    }

    with clean_graph.session(database=database) as session:
        first = session.execute_write(merge_version, **kwargs)
        second = session.execute_write(merge_version, **kwargs)

    # Same identity both times — the second call resolved to the first's version.
    assert first == second
    records, _, _ = clean_graph.execute_query(
        "MATCH (v:DocumentVersion) RETURN count(v) AS total", database_=database
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_merge_version_raises_when_the_document_does_not_exist(clean_graph, database):
    """A confidently-wrong id for a version that was never written would poison
    every later phase that chunks or extracts against it."""
    with (
        clean_graph.session(database=database) as session,
        pytest.raises(UnknownDocumentError),
    ):
        session.execute_write(
            merge_version,
            document_slug="missing",
            effective_date=date(2026, 4, 1),
            checksum="abc",
            source_uri="file:///d.pdf",
        )


@pytest.mark.integration
def test_merge_version_raises_on_a_same_date_checksum_conflict(clean_graph, database):
    """Same effective date, different content — a corrected reissue ("Change 1")
    or a distinct edition; the graph can't tell, so it must not guess."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )

    with clean_graph.session(database=database) as session:
        session.execute_write(
            merge_version,
            document_slug="d",
            effective_date=date(2026, 4, 1),
            checksum="original-checksum",
            source_uri="file:///d.pdf",
        )
        with pytest.raises(VersionConflictError):
            session.execute_write(
                merge_version,
                document_slug="d",
                effective_date=date(2026, 4, 1),
                checksum="different-checksum",
                source_uri="file:///d-reissue.pdf",
            )

    # The failed ingest changed nothing: the original checksum is still recorded.
    records, _, _ = clean_graph.execute_query(
        "MATCH (v:DocumentVersion {version_id: 'd@2026-04-01'}) "
        "RETURN v.checksum AS checksum",
        database_=database,
    )
    assert [r["checksum"] for r in records] == ["original-checksum"]


def _add(driver, database, slug, effective_date, checksum):
    with driver.session(database=database) as session:
        session.execute_write(
            merge_version,
            document_slug=slug,
            effective_date=effective_date,
            checksum=checksum,
            source_uri=f"file:///{checksum}.pdf",
        )


@pytest.mark.integration
def test_a_newer_edition_supersedes_the_older_one(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2024, 1, 1), "old")
    _add(clean_graph, database, "d", date(2026, 1, 1), "new")

    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [("d@2026-01-01", "d@2024-01-01")]


@pytest.mark.integration
def test_the_chain_is_rebuilt_not_appended(clean_graph, database):
    """An edition ingested out of order must not leave a wrong chain behind."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2024, 1, 1), "a")
    _add(clean_graph, database, "d", date(2026, 1, 1), "c")
    with clean_graph.session(database=database) as session:
        session.execute_write(link_supersession, "d")

    # The 2025 edition arrives last but belongs in the middle.
    _add(clean_graph, database, "d", date(2025, 1, 1), "b")
    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 2
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older "
        "ORDER BY newer.version_id",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [
        ("d@2025-01-01", "d@2024-01-01"),
        ("d@2026-01-01", "d@2025-01-01"),
    ]


@pytest.mark.integration
def test_a_single_edition_has_no_supersession(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2026, 1, 1), "only")

    with clean_graph.session(database=database) as session:
        assert session.execute_write(link_supersession, "d") == 0


@pytest.mark.integration
def test_rebuilding_one_document_leaves_another_chain_untouched(clean_graph, database):
    """REBUILD_SUPERSESSION is the only place this codebase deletes relationships.
    It must delete only the rebuilt document's own chain."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'}), "
        "(:Document {slug: 'other', name: 'Other'})",
        database_=database,
    )
    _add(clean_graph, database, "d", date(2024, 1, 1), "a")
    _add(clean_graph, database, "d", date(2026, 1, 1), "c")
    _add(clean_graph, database, "other", date(2024, 1, 1), "x")
    _add(clean_graph, database, "other", date(2026, 1, 1), "y")

    with clean_graph.session(database=database) as session:
        session.execute_write(link_supersession, "d")
        session.execute_write(link_supersession, "other")

    # A mid-chain edition arrives for d only. Rebuilding d must not touch other's chain.
    _add(clean_graph, database, "d", date(2025, 1, 1), "b")
    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 2
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older "
        "ORDER BY newer.version_id",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [
        ("d@2025-01-01", "d@2024-01-01"),
        ("d@2026-01-01", "d@2025-01-01"),
        ("other@2026-01-01", "other@2024-01-01"),
    ]


@pytest.mark.integration
def test_an_authority_issues_a_version(clean_graph, database):
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", date(2026, 1, 1), "x")

    with clean_graph.session(database=database) as session:
        session.execute_write(merge_authority, slug="usd-c", name="Under Secretary of Defense (Comptroller)")
        session.execute_write(attach_authority, version_id="d@2026-01-01", authority_slug="usd-c")

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'd@2026-01-01'})-[:ISSUED_BY]->(a:Authority) "
        "RETURN a.name AS name",
        database_=database,
    )
    assert [r["name"] for r in records] == ["Under Secretary of Defense (Comptroller)"]


@pytest.mark.integration
def test_reference_nodes_are_idempotent(clean_graph, database):
    with clean_graph.session(database=database) as session:
        for _ in range(2):
            session.execute_write(merge_authority, slug="dla", name="Defense Logistics Agency")
            session.execute_write(merge_entity, slug="dla-j8", name="DLA J8", kind="directorate")

    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Authority) WITH count(a) AS authorities "
        "MATCH (e:Entity) RETURN authorities, count(e) AS entities",
        database_=database,
    )
    assert (records[0]["authorities"], records[0]["entities"]) == (1, 1)


@pytest.mark.integration
def test_a_re_merge_does_not_rewrite_a_recorded_name(clean_graph, database):
    """ON CREATE SET protects against silent rewrites on re-ingest.

    A re-ingest correcting a name is a decision a human should make, not a
    side effect. This test verifies that a second ingest with a different name
    leaves the original name untouched — ON CREATE SET is not bare SET.
    """
    with clean_graph.session(database=database) as session:
        # First ingest: authority with original name
        session.execute_write(merge_authority, slug="usd-c", name="Under Secretary of Defense (Comptroller)")
        # Re-ingest: same slug, different name (e.g., a corrected abbreviation)
        session.execute_write(merge_authority, slug="usd-c", name="USD(C)")

    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Authority {slug: 'usd-c'}) RETURN a.name AS name",
        database_=database,
    )
    # The original name should be preserved, not overwritten
    assert [r["name"] for r in records] == ["Under Secretary of Defense (Comptroller)"]

    # Same test for Entity, varying both name and kind
    with clean_graph.session(database=database) as session:
        # First ingest: entity with original name and kind
        session.execute_write(merge_entity, slug="j8", name="DLA J8", kind="directorate")
        # Re-ingest: same slug, different name and kind
        session.execute_write(merge_entity, slug="j8", name="Joint Logistics", kind="division")

    records, _, _ = clean_graph.execute_query(
        "MATCH (e:Entity {slug: 'j8'}) RETURN e.name AS name, e.kind AS kind",
        database_=database,
    )
    # Original attributes should be preserved
    assert [(r["name"], r["kind"]) for r in records] == [("DLA J8", "directorate")]


@pytest.mark.integration
def test_ingesting_a_pdf_records_a_version(client_with_auth, tmp_path):
    """The single-document path versions; the manifest path does not."""
    response = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    assert response.status_code == 200
    slug = response.json()["document"]["slug"]

    versions = client_with_auth.get(f"/documents/{slug}/versions")
    assert versions.status_code == 200
    body = versions.json()
    assert len(body) == 1
    assert body[0]["checksum"]
    assert body[0]["supersedes"] is None


@pytest.mark.integration
def test_re_ingesting_the_same_pdf_adds_no_version(client_with_auth):
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    slug = first.json()["document"]["slug"]
    client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})

    versions = client_with_auth.get(f"/documents/{slug}/versions").json()
    assert len(versions) == 1


@pytest.mark.integration
def test_the_manifest_path_creates_no_versions(client_with_auth):
    """A CSV of citations describes no edition — inventing one would be a lie."""
    client_with_auth.post(
        "/ingest", json={"filename": "dod_policy_references_08122026.csv"}
    )
    documents = client_with_auth.get("/documents").json()
    assert documents  # sanity: the corpus loaded

    versions = client_with_auth.get(f"/documents/{documents[0]['slug']}/versions").json()
    assert versions == []
