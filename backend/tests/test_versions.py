import hashlib
from datetime import date
from pathlib import Path

import pytest

from policy_grapher import ingest as ingest_module
from policy_grapher.sources.document import ExtractedDocument, ExtractionReport
from policy_grapher.versions import (
    UnknownDocumentError,
    VersionConflictError,
    link_supersession,
    merge_version,
    version_id,
)

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


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
    # 500001p.pdf's cover states both "Effective: September 9, 2020" and "Change 1
    # Effective: July 28, 2022" — the file on disk is the Change-1-incorporated
    # edition, so the extracted date must be the latter, not the base date.
    assert body[0]["effective_date"] == "2022-07-28"


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


@pytest.mark.integration
def test_a_version_conflict_is_a_409_at_the_ingest_boundary(client_with_auth, monkeypatch):
    """ADR-011: the operator decides between a better scan and a genuine reissue —
    but only if the API surfaces the conflict instead of discarding it as a 500.

    The second ingest is forced (via a patched `extract_document`) to resolve to
    the same instrument name and the same effective date as the first, so it
    collides on version identity; only the underlying file's bytes — and hence
    the checksum computed from them — actually differ.
    """
    first = client_with_auth.post("/ingest", json={"filename": "500001p.pdf"})
    assert first.status_code == 200
    assert first.json()["document"]["slug"] == "dodd-5000-01"

    def same_edition_different_file(path):
        return ExtractedDocument(
            name="DoDD 5000.01",
            references=(),
            self_references_skipped=0,
            report=ExtractionReport(
                format="modern", section_found=True, attributed=(), unattributed=()
            ),
            effective_date=date(2022, 7, 28),
        )

    monkeypatch.setattr(ingest_module.pdf, "extract_document", same_edition_different_file)

    second = client_with_auth.post("/ingest", json={"filename": "500088p.pdf"})

    assert second.status_code == 409
    detail = second.json()["detail"]
    first_checksum = hashlib.sha256((SAMPLES / "500001p.pdf").read_bytes()).hexdigest()
    second_checksum = hashlib.sha256((SAMPLES / "500088p.pdf").read_bytes()).hexdigest()
    assert first_checksum in detail
    assert second_checksum in detail


@pytest.mark.integration
def test_an_undated_edition_sorts_as_the_oldest(clean_graph, database):
    """ADR-011's named limitation: with no effective_date to anchor on, an
    undated edition sorts before every dated one — not after."""
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'd', name: 'D'})", database_=database
    )
    _add(clean_graph, database, "d", None, "undated")
    _add(clean_graph, database, "d", date(2020, 1, 1), "dated")

    with clean_graph.session(database=database) as session:
        edges = session.execute_write(link_supersession, "d")

    assert edges == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (newer:DocumentVersion)-[:SUPERSEDES]->(older:DocumentVersion) "
        "RETURN newer.version_id AS newer, older.version_id AS older",
        database_=database,
    )
    assert [(r["newer"], r["older"]) for r in records] == [
        ("d@2020-01-01", "d@undated")
    ]


@pytest.mark.integration
def test_list_versions_is_scoped_ordered_and_points_the_right_direction(
    client_with_auth, clean_graph, database
):
    """One fixture pins three independently-mutable properties of LIST_VERSIONS:
    slug scoping, SUPERSEDES direction, and the ORDER BY.

    Two documents, each with three versions, dates interleaved between them and
    inserted out of date order — so a scoping failure returns obviously foreign
    rows, and a missing ORDER BY does not accidentally match insertion order.
    """
    clean_graph.execute_query(
        "CREATE (:Document {slug: 'alpha-doc', name: 'Alpha'}), "
        "(:Document {slug: 'beta-doc', name: 'Beta'})",
        database_=database,
    )

    # Inserted out of date order on purpose, and with dates interleaved between
    # the two documents.
    _add(clean_graph, database, "alpha-doc", date(2024, 1, 1), "a3")
    _add(clean_graph, database, "beta-doc", date(2021, 1, 1), "b2")
    _add(clean_graph, database, "alpha-doc", date(2020, 1, 1), "a1")
    _add(clean_graph, database, "beta-doc", date(2023, 1, 1), "b3")
    _add(clean_graph, database, "alpha-doc", date(2022, 1, 1), "a2")
    _add(clean_graph, database, "beta-doc", date(2019, 1, 1), "b1")

    with clean_graph.session(database=database) as session:
        session.execute_write(link_supersession, "alpha-doc")
        session.execute_write(link_supersession, "beta-doc")

    alpha = client_with_auth.get("/documents/alpha-doc/versions")
    assert alpha.status_code == 200
    assert [
        (v["version_id"], v["effective_date"], v["checksum"], v["supersedes"])
        for v in alpha.json()
    ] == [
        ("alpha-doc@2020-01-01", "2020-01-01", "a1", None),
        ("alpha-doc@2022-01-01", "2022-01-01", "a2", "alpha-doc@2020-01-01"),
        ("alpha-doc@2024-01-01", "2024-01-01", "a3", "alpha-doc@2022-01-01"),
    ]

    beta = client_with_auth.get("/documents/beta-doc/versions")
    assert beta.status_code == 200
    assert [
        (v["version_id"], v["effective_date"], v["checksum"], v["supersedes"])
        for v in beta.json()
    ] == [
        ("beta-doc@2019-01-01", "2019-01-01", "b1", None),
        ("beta-doc@2021-01-01", "2021-01-01", "b2", "beta-doc@2019-01-01"),
        ("beta-doc@2023-01-01", "2023-01-01", "b3", "beta-doc@2021-01-01"),
    ]
