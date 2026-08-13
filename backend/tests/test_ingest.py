from pathlib import Path

import pytest
from neo4j import RoutingControl

from policy_grapher.csv_source import parse_corpus
from policy_grapher.ingest import ingest_file, ingest_parsed
from policy_grapher.slugs import hash_suffix

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "samples"
SAMPLE = "dod_policy_references_08122026.csv"


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "corpus.csv"
    path.write_text(body, encoding="utf-8")
    return path


def count(driver, database, cypher: str) -> int:
    records, _, _ = driver.execute_query(
        cypher, database_=database, routing_=RoutingControl.READ
    )
    return records[0]["n"]


def test_small_corpus_creates_nodes_and_edges(clean_graph, database, tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        'A,"[\'B\', \'C\']",Root Reference\n'
        'B,"[\'C\']",Sub-Reference\n',
    )
    result = ingest_parsed(clean_graph, database, parse_corpus(path))

    assert result.nodes_created == 3
    assert result.relationships_created == 3
    assert count(clean_graph, database, "MATCH (d:Document) RETURN count(d) AS n") == 3


def test_external_documents_carry_the_label_and_no_reference_role(
    clean_graph, database, tmp_path
):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
    )
    ingest_parsed(clean_graph, database, parse_corpus(path))

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: 'B'}) "
        "RETURN d:External AS is_external, d.reference_role AS role",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["is_external"] is True
    assert records[0]["role"] is None

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: 'A'}) "
        "RETURN d:External AS is_external, d.reference_role AS role",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["is_external"] is False
    assert records[0]["role"] == "Root Reference"


def test_self_references_create_no_loop(clean_graph, database, tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\nA,"[\'A\', \'B\']",Sub-Reference\n',
    )
    result = ingest_parsed(clean_graph, database, parse_corpus(path))

    assert result.self_references_skipped == 1
    loops = count(
        clean_graph,
        database,
        "MATCH (d:Document)-[:REFERENCES]->(d) RETURN count(*) AS n",
    )
    assert loops == 0


def test_a_document_transitions_correctly_in_either_direction(
    clean_graph, database, tmp_path
):
    """A node's :External label and reference_role must track its most recent role
    across ingests, in both directions: cited-only -> corpus, and corpus -> cited-only.
    """
    first = tmp_path / "first.csv"
    first.write_text(
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(first))

    # Before the second ingest: A is corpus (has a role), B is external (no role).
    def fetch(name: str) -> dict:
        records, _, _ = clean_graph.execute_query(
            "MATCH (d:Document {name: $name}) "
            "RETURN d:External AS is_external, d.reference_role AS role",
            {"name": name},
            database_=database,
            routing_=RoutingControl.READ,
        )
        return {"is_external": records[0]["is_external"], "role": records[0]["role"]}

    assert fetch("A") == {"is_external": False, "role": "Root Reference"}
    assert fetch("B") == {"is_external": True, "role": None}

    # Second file flips both: B becomes the corpus row (cited-only -> corpus), and A
    # drops out of the corpus, remaining only as B's citation target (corpus ->
    # cited-only).
    second = tmp_path / "second.csv"
    second.write_text(
        'Document Name,References,Type\nB,"[\'A\']",Sub-Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(second))

    assert fetch("B") == {"is_external": False, "role": "Sub-Reference"}
    assert fetch("A") == {"is_external": True, "role": None}


def test_reingesting_the_sample_corpus_creates_nothing(clean_graph, database):
    first = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    assert first.nodes_created == 438
    assert first.relationships_created == 672

    second = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    assert second.nodes_created == 0
    assert second.relationships_created == 0

    assert count(clean_graph, database, "MATCH (d:Document) RETURN count(d) AS n") == 438
    assert count(
        clean_graph, database, "MATCH ()-[r:REFERENCES]->() RETURN count(r) AS n"
    ) == 672


def test_sample_corpus_node_split_and_skips(clean_graph, database):
    result = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    assert result.self_references_skipped == 4
    assert len(result.suspected_duplicates) == 2

    corpus = count(
        clean_graph,
        database,
        "MATCH (d:Document) WHERE NOT d:External RETURN count(d) AS n",
    )
    external = count(
        clean_graph, database, "MATCH (d:External) RETURN count(d) AS n"
    )
    assert corpus == 23
    assert external == 415


def test_slugs_are_identical_across_a_reset_and_reingest(clean_graph, database):
    from policy_grapher.db import clear_graph

    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    before = {r["name"]: r["slug"] for r in records}

    clear_graph(clean_graph, database)
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    after = {r["name"]: r["slug"] for r in records}

    assert before == after
    assert len(set(after.values())) == 438


def test_the_two_corpus_slug_collisions_are_resolved_by_hash(clean_graph, database):
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    a, b = "Military Standard 882E", "Military-Standard 882E"
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.name IN $names RETURN d.name AS name, d.slug AS slug",
        {"names": [a, b]},
        database_=database,
        routing_=RoutingControl.READ,
    )
    slugs = {r["name"]: r["slug"] for r in records}
    assert slugs[a] == f"military-standard-882e-{hash_suffix(a)}"
    assert slugs[b] == f"military-standard-882e-{hash_suffix(b)}"


def test_ingest_endpoint_returns_the_result(client_with_graph):
    response = client_with_graph.post("/ingest", json={"filename": SAMPLE})
    assert response.status_code == 200
    body = response.json()
    assert body["nodes_created"] == 438
    assert body["relationships_created"] == 672
    assert body["self_references_skipped"] == 4
    assert len(body["suspected_duplicates"]) == 2
