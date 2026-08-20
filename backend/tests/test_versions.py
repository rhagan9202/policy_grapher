from datetime import date

import pytest

from policy_grapher.versions import (
    UnknownDocumentError,
    VersionConflictError,
    link_supersession,
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
