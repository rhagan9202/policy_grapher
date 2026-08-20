from datetime import date

import pytest

from policy_grapher.versions import merge_version, version_id


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
