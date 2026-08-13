"""Provenance: which ingest described which document, and the :External view of it."""

import pytest
from neo4j import RoutingControl

from policy_grapher.sources import provenance


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


# --- source_id, no database ---------------------------------------------

def test_source_id_is_kind_and_filename():
    assert provenance.source_id(provenance.MANIFEST, "corpus.csv") == "manifest:corpus.csv"
    assert provenance.source_id(provenance.DOCUMENT, "500001p.pdf") == "document:500001p.pdf"


# --- against the real driver -------------------------------------------

@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


SAMPLE = "dod_policy_references_08122026.csv"


@pytest.mark.integration
def test_no_document_disagrees_with_its_provenance(client_with_graph, driver, database):
    """:External is a view. If a write path forgets to refresh it, this is what says so.

    All three write paths run, POST /documents included: its statements are the
    only ones not wrapped in a single transaction, which makes it the likeliest
    place for the view to drift from the provenance it is derived from.
    """
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    client_with_graph.post("/ingest", json={"filename": "500001p.pdf"})
    client_with_graph.post("/documents", json={"name": "Hand-Created Policy"})

    records, _, _ = driver.execute_query(
        "MATCH (d:Document) "
        "WITH d, EXISTS { (:Source)-[:DESCRIBES]->(d) } AS described "
        "WHERE described = d:External "
        "RETURN collect(d.slug)[..10] AS wrong, count(*) AS total",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["total"] == 0, records[0]["wrong"]
