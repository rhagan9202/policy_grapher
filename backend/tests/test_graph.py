from pathlib import Path

import pytest

from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.ingest import ingest_file

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data"
SAMPLE = "dod_policy_references_08122026.csv"


@pytest.fixture
def loaded(clean_graph, database):
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    return clean_graph, database


def test_default_view_is_the_corpus_only(loaded):
    driver, database = loaded
    result = build_graph(driver, database)

    assert result.returned_nodes == 23
    assert result.total_nodes == 23
    assert result.truncated is False
    assert all(node.is_external is False for node in result.nodes)
    assert all(node.reference_role is not None for node in result.nodes)
    assert len(result.edges) == 72


def test_including_externals_hits_the_render_cap(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=300)

    assert result.total_nodes == 438
    assert result.returned_nodes == 300
    assert result.truncated is True
    assert len(result.nodes) == 300


def test_every_corpus_document_survives_truncation(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=300)

    corpus = [node for node in result.nodes if not node.is_external]
    assert len(corpus) == 23


def test_corpus_nodes_win_even_when_the_cap_is_below_their_count(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=5)

    assert result.returned_nodes == 23
    assert all(node.is_external is False for node in result.nodes)
    assert result.truncated is True


def test_truncation_is_deterministic(loaded):
    driver, database = loaded
    first = build_graph(driver, database, include_external=True, limit=300)
    second = build_graph(driver, database, include_external=True, limit=300)

    assert [n.id for n in first.nodes] == [n.id for n in second.nodes]
    assert [(e.source, e.target) for e in first.edges] == [
        (e.source, e.target) for e in second.edges
    ]


def test_highest_degree_external_is_kept(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=300)

    names = {node.label for node in result.nodes if node.is_external}
    assert "United States Code, Title 10" in names
    assert "Deputy Secretary of Defense Memorandum" in names


def test_tie_break_keeps_the_lexicographically_smaller_slug_at_the_boundary(loaded):
    # With a 300-node cap and 23 corpus documents, the external budget is 277.
    # Measured against the real corpus, index 276 (the last kept slot) and index
    # 277 (the first dropped slot) are both degree-1 externals, so only the
    # slug ASC tie-break decides which one survives. Reversing that ORDER BY
    # clause to slug DESC keeps every other test in this file green, because
    # every other test asserts counts or degrees far from this boundary. This
    # test pins the two concrete slugs straddling that boundary directly.
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=300)

    ids = {node.id for node in result.nodes}
    assert "executive-order-12580" in ids
    assert "executive-order-12626" not in ids


def test_a_zero_limit_disables_the_cap(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=0)

    assert result.returned_nodes == 438
    assert result.truncated is False
    assert len(result.edges) == 672


def test_expanding_a_document_adds_only_its_external_neighbours(loaded):
    driver, database = loaded
    default = build_graph(driver, database)
    expanded = build_graph(driver, database, expand="dodi-3115-14")

    assert expanded.returned_nodes > default.returned_nodes
    added = {n.id for n in expanded.nodes} - {n.id for n in default.nodes}
    assert added
    assert all(
        node.is_external for node in expanded.nodes if node.id in added
    )


def test_expanding_an_unknown_slug_raises(loaded):
    driver, database = loaded
    with pytest.raises(UnknownDocumentError):
        build_graph(driver, database, expand="no-such-document")


def test_edges_never_dangle(loaded):
    driver, database = loaded
    result = build_graph(driver, database, include_external=True, limit=300)

    ids = {node.id for node in result.nodes}
    for edge in result.edges:
        assert edge.source in ids
        assert edge.target in ids


def test_graph_endpoint_serves_the_default_view(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    response = client_with_graph.get("/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["returned_nodes"] == 23
    assert body["truncated"] is False


def test_graph_endpoint_honours_query_parameters(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    response = client_with_graph.get(
        "/graph", params={"include_external": "true", "limit": 300}
    )

    body = response.json()
    assert body["total_nodes"] == 438
    assert body["returned_nodes"] == 300
    assert body["truncated"] is True


def test_graph_endpoint_returns_404_for_an_unknown_expand_slug(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    response = client_with_graph.get("/graph", params={"expand": "no-such-document"})
    assert response.status_code == 404
