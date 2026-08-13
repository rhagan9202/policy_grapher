from pathlib import Path

import pytest
from neo4j import RoutingControl

from policy_grapher.documents import add_reference
from policy_grapher.graph import UnknownDocumentError, build_graph
from policy_grapher.ingest import ingest_file, ingest_parsed
from policy_grapher.sources.manifest import parse_corpus

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "samples"
SAMPLE = "dod_policy_references_08122026.csv"


def write_csv(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def slugs_by_name(driver, database) -> dict[str, str]:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return {r["name"]: r["slug"] for r in records}


def is_external(driver, database, name: str) -> bool:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document {name: $name}) RETURN d:External AS is_external",
        {"name": name},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["is_external"]


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

    # Verified by hand against the live stack: GET /graph?expand=dodi-3115-14
    # returns returned_nodes 29, total_nodes 29, truncated false.
    assert expanded.returned_nodes == 29
    assert expanded.total_nodes == 29
    assert expanded.truncated is False

    assert expanded.returned_nodes > default.returned_nodes
    added = {n.id for n in expanded.nodes} - {n.id for n in default.nodes}
    assert added
    assert all(
        node.is_external for node in expanded.nodes if node.id in added
    )


def test_expand_ranks_external_neighbours_by_true_degree(
    clean_graph, database, tmp_path
):
    """Regression coverage for the degree-doubling bug in EXTERNAL_NEIGHBOURS,
    adapted for ADR-007.

    The bug needed an :External neighbour with a *reverse* edge back to the
    expand node — the undirected match matched it twice, and without `WITH
    DISTINCT d` ahead of the degree count, its degree was doubled. Through the
    manifest path alone, that scenario cannot arise: only a corpus row is the
    source of a manifest-created REFERENCES edge, and any document that has
    ever been a corpus row is described forever (see
    provenance.REFRESH_EXTERNAL), so a node with a *manifest-created* outgoing
    edge can never be :External. (A reverse edge can still be added directly
    through the documents API without describing anything — see
    test_expand_ranks_external_neighbours_with_a_user_added_reverse_edge for
    that path's guard.) This test keeps the remaining, manifest-only coverage:
    D and E are both cited-only in this manifest, so both stay :External, and
    a one-slot external budget must keep the one with the genuinely higher
    degree — E, cited by S, F and G (3), over D, cited by S alone (1).
    """
    first = write_csv(
        tmp_path,
        "first.csv",
        'Document Name,References,Type\n'
        'S,"[\'D\', \'E\']",Root Reference\n'
        'F,"[\'E\']",Sub-Reference\n'
        'G,"[\'E\']",Sub-Reference\n',
    )
    ingest_parsed(clean_graph, database, parse_corpus(first), first.name)

    # Corpus is S, F, G (3 nodes); a budget of 4 leaves exactly one external slot.
    result = build_graph(clean_graph, database, expand="s", limit=4)

    external_ids = {node.id for node in result.nodes if node.is_external}
    assert external_ids == {"e"}


def test_expand_ranks_external_neighbours_with_a_user_added_reverse_edge(
    clean_graph, database, tmp_path
):
    """Regression guard for the degree-doubling bug in EXTERNAL_NEIGHBOURS,
    exercised through the one path that can still produce it.

    The manifest path can never give an :External document an outgoing edge
    (see test_expand_ranks_external_neighbours_by_true_degree's docstring).
    But `documents.add_reference` — the code behind
    `POST /documents/{slug}/references/{target_slug}` — only checks that both
    slugs exist; it never inspects :External and never calls
    REFRESH_EXTERNAL. A user is free to add D -> S even though D is external:
    under ADR-007 that is a legitimate state, since an asserted edge is not a
    description. That reproduces exactly the bidirectional match (S <-> D)
    the original bug needed. Without `WITH DISTINCT d` ahead of the degree
    count, D's undirected match against S is counted twice, so its two real
    edges are counted four times (2 x 2 = 4), wrongly outranking E's genuine
    degree of 3.
    """
    first = write_csv(
        tmp_path,
        "first.csv",
        'Document Name,References,Type\n'
        'S,"[\'D\', \'E\']",Root Reference\n'
        'F,"[\'E\']",Sub-Reference\n'
        'G,"[\'E\']",Sub-Reference\n',
    )
    ingest_parsed(clean_graph, database, parse_corpus(first), first.name)

    slugs = slugs_by_name(clean_graph, database)
    # A user-added reverse edge is not a description: D stays external.
    add_reference(clean_graph, database, slugs["D"], slugs["S"])
    assert is_external(clean_graph, database, "D") is True

    # Corpus is S, F, G (3 nodes); a budget of 4 leaves exactly one external slot.
    result = build_graph(clean_graph, database, expand="s", limit=4)

    external_ids = {node.id for node in result.nodes if node.is_external}
    assert external_ids == {"e"}


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


def test_graph_endpoint_honours_a_valid_expand_slug(client_with_graph):
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    response = client_with_graph.get("/graph", params={"expand": "dodi-3115-14"})

    assert response.status_code == 200
    body = response.json()
    # Verified by hand against the live stack: GET /graph?expand=dodi-3115-14
    # returns returned_nodes 29, total_nodes 29, truncated false.
    assert body["returned_nodes"] == 29
    assert body["total_nodes"] == 29
    assert body["truncated"] is False


def test_graph_endpoint_404s_for_an_unknown_expand_slug_regardless_of_include_external(
    client_with_graph,
):
    """B3 regression: include_external must not let an unknown expand slug validate."""
    client_with_graph.post("/ingest", json={"filename": SAMPLE})
    response = client_with_graph.get(
        "/graph", params={"include_external": "true", "expand": "no-such-document"}
    )
    assert response.status_code == 404
