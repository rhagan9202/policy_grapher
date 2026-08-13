"""Provenance: which ingest described which document, and the :External view of it."""

import pytest
from neo4j import RoutingControl

from policy_grapher.sources import provenance

pytestmark = pytest.mark.integration


def labels_of(driver, database, slug: str) -> set[str]:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: $slug}) RETURN labels(d) AS labels",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return set(records[0]["labels"])


def make_document(driver, database, slug: str) -> None:
    driver.execute_query(
        "CREATE (d:Document {slug: $slug, name: $slug})",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.WRITE,
    )


def test_source_id_is_kind_and_filename():
    assert provenance.source_id(provenance.MANIFEST, "corpus.csv") == "manifest:corpus.csv"
    assert provenance.source_id(provenance.DOCUMENT, "500001p.pdf") == "document:500001p.pdf"


def test_a_described_document_loses_external_and_an_undescribed_one_gains_it(
    clean_graph, database
):
    make_document(clean_graph, database, "described")
    make_document(clean_graph, database, "cited-only")
    clean_graph.execute_query(
        provenance.MERGE_SOURCE,
        {"id": "manifest:x.csv", "kind": "manifest", "filename": "x.csv"},
        database_=database,
        routing_=RoutingControl.WRITE,
    )
    clean_graph.execute_query(
        provenance.DESCRIBES,
        {"id": "manifest:x.csv", "slugs": ["described"]},
        database_=database,
        routing_=RoutingControl.WRITE,
    )

    clean_graph.execute_query(
        provenance.REFRESH_EXTERNAL,
        {"slugs": ["described", "cited-only"]},
        database_=database,
        routing_=RoutingControl.WRITE,
    )

    assert labels_of(clean_graph, database, "described") == {"Document"}
    assert labels_of(clean_graph, database, "cited-only") == {"Document", "External"}


def test_refreshing_is_idempotent(clean_graph, database):
    make_document(clean_graph, database, "cited-only")

    for _ in range(2):
        clean_graph.execute_query(
            provenance.REFRESH_EXTERNAL,
            {"slugs": ["cited-only"]},
            database_=database,
            routing_=RoutingControl.WRITE,
        )

    assert labels_of(clean_graph, database, "cited-only") == {"Document", "External"}


def test_recording_the_same_source_twice_creates_one_node(clean_graph, database):
    for _ in range(2):
        clean_graph.execute_query(
            provenance.MERGE_SOURCE,
            {"id": "document:a.pdf", "kind": "document", "filename": "a.pdf"},
            database_=database,
            routing_=RoutingControl.WRITE,
        )

    records, _, _ = clean_graph.execute_query(
        "MATCH (s:Source) RETURN count(s) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 1
