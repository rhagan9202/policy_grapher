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
    # A response that dropped 138 nodes must say on what basis, the same as the
    # focused mode does. Null is defined on the field as "nothing was dropped",
    # so leaving it unset here claimed completeness on a truncated answer.
    assert result.truncation_basis is not None


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


def test_graph_endpoint_serves_the_default_view(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get("/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["returned_nodes"] == 23
    assert body["truncated"] is False


def test_graph_endpoint_honours_query_parameters(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get(
        "/graph", params={"include_external": "true", "limit": 300}
    )

    body = response.json()
    assert body["total_nodes"] == 438
    assert body["returned_nodes"] == 300
    assert body["truncated"] is True


def test_graph_endpoint_returns_404_for_an_unknown_expand_slug(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get("/graph", params={"expand": "no-such-document"})
    assert response.status_code == 404


def test_graph_endpoint_honours_a_valid_expand_slug(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get("/graph", params={"expand": "dodi-3115-14"})

    assert response.status_code == 200
    body = response.json()
    # Verified by hand against the live stack: GET /graph?expand=dodi-3115-14
    # returns returned_nodes 29, total_nodes 29, truncated false.
    assert body["returned_nodes"] == 29
    assert body["total_nodes"] == 29
    assert body["truncated"] is False


def test_graph_endpoint_404s_for_an_unknown_expand_slug_regardless_of_include_external(
    client_with_auth,
):
    """B3 regression: include_external must not let an unknown expand slug validate."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get(
        "/graph", params={"include_external": "true", "expand": "no-such-document"}
    )
    assert response.status_code == 404


def test_a_focused_view_holds_the_neighbourhood_and_nothing_else(loaded):
    """R5: the focused view is not the corpus filtered, it is a different set.

    `dodi-3115-14` is a corpus document with a handful of references, so at depth
    one the answer is itself plus what it cites plus what cites it — and none of
    the other twenty-two corpus documents, which a corpus-first view would draw
    unconditionally.
    """
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14")

    ids = {node.id for node in graph.nodes}
    assert "dodi-3115-14" in ids

    expected, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: 'dodi-3115-14'})-[:REFERENCES]-(n:Document) "
        "RETURN collect(DISTINCT n.slug) AS slugs",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert ids == {"dodi-3115-14", *expected[0]["slugs"]}

    corpus_total = build_graph(driver, database).returned_nodes
    assert len(ids) < corpus_total, (
        "a focused view that is not smaller than the corpus view is the corpus "
        "view, which is what this mode exists to stop being"
    )


def test_documents_outside_the_neighbourhood_are_never_admitted(loaded):
    """The defect this unit was written to fix.

    An allocation that put the focused document first and then let the wider
    corpus fill the remaining budget looks like a priority order. It is not: this
    corpus holds 23 documents against a cap of 300, so that second tier always
    fits whole and every focused request would quietly return the corpus.
    """
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14", limit=300)

    ids = {node.id for node in graph.nodes}
    reachable, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: 'dodi-3115-14'})-[:REFERENCES]-(n:Document) "
        "RETURN collect(DISTINCT n.slug) AS slugs",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert ids == {"dodi-3115-14", *reachable[0]["slugs"]}


def test_a_truncated_neighbourhood_says_so_and_on_what_basis(loaded):
    """AE6: a partial neighbourhood must not render like a complete one."""
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14", limit=3)

    assert graph.returned_nodes == 3
    assert graph.truncated is True
    assert graph.truncation_basis is not None
    assert graph.total_nodes > graph.returned_nodes


def test_an_untruncated_neighbourhood_claims_no_basis(loaded):
    """Null and "nothing was cut" are the same thing for this field, unlike the
    parse outcome, where absent and false are different facts."""
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14")

    assert graph.truncated is False
    assert graph.truncation_basis is None


def test_the_focused_document_survives_any_budget(loaded):
    """A view that dropped the thing it is a view of would answer nothing."""
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14", limit=1)

    assert [node.id for node in graph.nodes] == ["dodi-3115-14"]
    assert graph.truncated is True


def test_depth_two_reaches_the_neighbours_neighbours(loaded):
    """R5 expands outward a degree at a time, so degree two is a superset."""
    driver, database = loaded
    near = build_graph(driver, database, focus="dodi-3115-14", depth=1)
    far = build_graph(driver, database, focus="dodi-3115-14", depth=2)

    near_ids = {node.id for node in near.nodes}
    far_ids = {node.id for node in far.nodes}
    assert near_ids < far_ids
    assert far.nodes[0].id == "dodi-3115-14", "the focus stays first at any depth"


def test_focusing_an_unknown_slug_raises(loaded):
    """Refused distinctly from a known document that simply has no neighbours."""
    driver, database = loaded
    with pytest.raises(UnknownDocumentError):
        build_graph(driver, database, focus="no-such-document")


def test_the_corpus_wide_mode_is_unchanged_by_the_focused_one(loaded):
    """This unit changes which mode is primary, not which modes exist."""
    driver, database = loaded
    graph = build_graph(driver, database)

    assert graph.returned_nodes == 23
    assert graph.truncated is False
    assert all(not node.is_external for node in graph.nodes)


def test_truncation_keeps_corpus_neighbours_over_external_ones(loaded):
    """The ordering the focused mode exists to get right, pinned by identity.

    Counting survivors is not enough: `dodi-3115-14` sits on exactly the corpus
    and external tier boundary, so reversing the priority at the sort still
    returns the same number of nodes and the same `truncated` flag. Only asking
    *which* nodes came back can tell the two apart — and dropping a corpus
    dependency to keep a more-cited external name is the failure this ordering
    was written to prevent.
    """
    driver, database = loaded
    corpus_neighbours, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: 'dodi-3115-14'})-[:REFERENCES]-(n:Document) "
        "WHERE NOT n:External "
        "RETURN collect(DISTINCT n.slug) AS slugs",
        database_=database,
        routing_=RoutingControl.READ,
    )
    expected = set(corpus_neighbours[0]["slugs"])
    assert expected, "fixture no longer has corpus neighbours to prioritise"

    graph = build_graph(
        driver, database, focus="dodi-3115-14", limit=1 + len(expected)
    )

    assert {node.id for node in graph.nodes} == {"dodi-3115-14", *expected}
    assert all(not node.is_external for node in graph.nodes)
    assert graph.truncated is True


def test_focused_edges_are_the_edges_between_returned_nodes(loaded):
    """Nothing else asserts edges, so a regression there would pass the suite."""
    driver, database = loaded
    graph = build_graph(driver, database, focus="dodi-3115-14")

    ids = {node.id for node in graph.nodes}
    expected, _, _ = driver.execute_query(
        "MATCH (s:Document)-[:REFERENCES]->(t:Document) "
        "WHERE s.slug IN $ids AND t.slug IN $ids "
        "RETURN collect([s.slug, t.slug]) AS pairs",
        {"ids": sorted(ids)},
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert {(e.source, e.target) for e in graph.edges} == {
        (pair[0], pair[1]) for pair in expected[0]["pairs"]
    }


def test_graph_endpoint_serves_a_focused_view(client_with_auth):
    """The eight build_graph tests never cross the router, and the router is
    what production traffic hits — it resolves the render cap before calling in,
    so the unbounded path those tests exercise is unreachable from a request."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get("/graph", params={"focus": "dodi-3115-14"})

    assert response.status_code == 200
    body = response.json()
    assert body["nodes"][0]["id"] == "dodi-3115-14"
    assert body["returned_nodes"] == body["total_nodes"]
    assert body["truncated"] is False
    assert body["truncation_basis"] is None


def test_graph_endpoint_honours_depth_on_a_focused_view(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    near = client_with_auth.get("/graph", params={"focus": "dodi-3115-14"})
    far = client_with_auth.get(
        "/graph", params={"focus": "dodi-3115-14", "depth": 2}
    )

    assert far.status_code == 200
    assert far.json()["returned_nodes"] > near.json()["returned_nodes"]


def test_graph_endpoint_rejects_a_depth_outside_its_bounds(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    for depth in (0, 4):
        response = client_with_auth.get(
            "/graph", params={"focus": "dodi-3115-14", "depth": depth}
        )
        assert response.status_code == 422, f"depth={depth} was accepted"


def test_graph_endpoint_404s_for_an_unknown_focus_slug(client_with_auth):
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get("/graph", params={"focus": "no-such-document"})
    assert response.status_code == 404


def test_graph_endpoint_refuses_focus_combined_with_the_corpus_parameters(
    client_with_auth,
):
    """Answering 200 while dropping a parameter the caller sent reads as though
    the narrower answer was the one they asked for."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    for params in (
        {"focus": "dodi-3115-14", "expand": "dodi-8500-01"},
        {"focus": "dodi-3115-14", "include_external": "true"},
        # Explicitly false, not merely absent: the caller still asked for
        # something the focused mode cannot honour.
        {"focus": "dodi-3115-14", "include_external": "false"},
    ):
        response = client_with_auth.get("/graph", params=params)
        assert response.status_code == 422, f"{params} was accepted"


def test_the_corpus_parameters_still_work_without_focus(client_with_auth):
    """The refusal above must not cost the existing mode its defaults."""
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    response = client_with_auth.get(
        "/graph", params={"include_external": "false", "expand": "dodi-3115-14"}
    )
    assert response.status_code == 200
    assert response.json()["returned_nodes"] == 29


def _seed_ladder(driver, database):
    """One document at each rung of the fidelity ladder, all cited by one hub.

    Seeded directly rather than through ingest and extraction: the ladder is a
    statement about graph topology — external membership, edition count,
    obligation count, reviewed-link count — and driving it through a real PDF
    would fix all four signals at once with no way to move a single rung.
    """
    driver.execute_query(
        """
        MERGE (hub:Document {slug: 'hub', name: 'Hub'})
        SET hub.references_section_found = true, hub.references_unattributed = []
        MERGE (hub)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'hub@1',
            checksum: 'h', source_uri: 'file:///h.pdf'})
        MERGE (cited:Document:External {slug: 'cited-only', name: 'Cited Only'})
        MERGE (manifest:Document {slug: 'manifest-only', name: 'Manifest Only'})
        MERGE (text:Document {slug: 'has-text', name: 'Has Text'})
        MERGE (text)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'text@1',
            checksum: 't', source_uri: 'file:///t.pdf'})
        MERGE (ob:Document {slug: 'has-obligations', name: 'Has Obligations'})
        MERGE (ob)-[:HAS_VERSION]->(obv:DocumentVersion {version_id: 'ob@1',
            checksum: 'o', source_uri: 'file:///o.pdf'})
        MERGE (obv)-[:MANDATES]->(:Obligation {obligation_id: 'ob-1',
            statement: 'The Director shall report.', modality: 'MUST', section_path: ['1']})
        MERGE (rev:Document {slug: 'has-reviewed', name: 'Has Reviewed'})
        MERGE (rev)-[:HAS_VERSION]->(revv:DocumentVersion {version_id: 'rev@1',
            checksum: 'r', source_uri: 'file:///r.pdf'})
        MERGE (revv)-[:MANDATES]->(ro:Obligation {obligation_id: 'rev-1',
            statement: 'The Secretary shall publish.', modality: 'MUST', section_path: ['1']})
        MERGE (upstream:Obligation {obligation_id: 'upstream-1',
            statement: 'The Department shall maintain.', modality: 'MUST', section_path: ['1']})
        MERGE (ro)-[:IMPLEMENTS]->(upstream)
        MERGE (hub)-[:REFERENCES]->(cited)
        MERGE (hub)-[:REFERENCES]->(manifest)
        MERGE (hub)-[:REFERENCES]->(text)
        MERGE (hub)-[:REFERENCES]->(ob)
        MERGE (hub)-[:REFERENCES]->(rev)
        """,
        database_=database,
    )


def _tiers(graph) -> dict[str, int]:
    return {node.id: node.fidelity_tier for node in graph.nodes}


def _node(graph, slug):
    return next(node for node in graph.nodes if node.id == slug)


def test_every_rung_of_the_fidelity_ladder_is_distinguishable(clean_graph, database):
    """R6: five states, told apart by four signals already in the graph.

    Each rung is reported as its own value, so a reader can tell a name the
    corpus only ever saw cited from a document whose links a person has
    actually reviewed. One assertion per rung rather than a spot check,
    because the ladder's whole purpose is that adjacent rungs differ.
    """
    _seed_ladder(clean_graph, database)
    graph = build_graph(clean_graph, database, focus="hub")

    assert _tiers(graph) == {
        "hub": 3,
        "cited-only": 1,
        "manifest-only": 2,
        "has-text": 3,
        "has-obligations": 4,
        "has-reviewed": 5,
    }


def test_the_tier_and_the_assessment_state_are_separate_axes(clean_graph, database):
    """AE2, and the collapse KTD1 forbids.

    A document at the top of the ladder whose references section was never
    located is a real state, and it must not render as one that genuinely
    cites nothing. Reading the resolution outcome as a sixth rung would erase
    exactly that difference, so the two are asserted on the same node.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-reviewed'}) "
        "SET d.references_section_found = false, d.references_unattributed = []",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    reviewed = _node(graph, "has-reviewed")
    assert reviewed.fidelity_tier == 5
    assert reviewed.assessment_state == "not_assessed"
    # Null rather than empty. An empty list here would say every name resolved,
    # about a document nothing has been read from — the exact claim the
    # null-versus-empty split on this field exists to stop.
    assert reviewed.unresolved_names is None


def test_a_document_that_resolved_every_name_is_not_one_that_cites_nothing(
    clean_graph, database
):
    """R10 on the assessment axis: the two empty-looking states differ."""
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-text'}) "
        "SET d.references_section_found = true, d.references_unattributed = []",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    assert _node(graph, "hub").assessment_state == "assessed_all_resolved"
    assert _node(graph, "has-text").assessment_state == "assessed_cites_nothing"


def test_unresolved_names_are_reported_and_retrievable_from_the_node(
    clean_graph, database
):
    """R7: the names, not merely a mark that some exist.

    An unresolved public law is a different thing from an unresolved DoD
    issuance the corpus should be holding, and only the names carry that.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-text'}) "
        "SET d.references_section_found = true, "
        "    d.references_unattributed = ['Public Law 99-145', 'Some Memorandum']",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    node = _node(graph, "has-text")
    assert node.assessment_state == "assessed_names_unresolved"
    assert node.unresolved_names == ["Public Law 99-145", "Some Memorandum"]


def test_a_located_section_with_only_unresolved_names_never_reads_as_citing_nothing(
    clean_graph, database
):
    """The false all-clear the design's own diagram would permit if read naively.

    A document whose section was located, that drew no edge because not one
    entry could be attributed, has resolved nothing — but it does not cite
    nothing. Reporting it as 'cites nothing' would assert a finding about a
    document the parser demonstrably failed to read, which is the shape
    ADR-015 exists to stop.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-text'}) "
        "SET d.references_section_found = true, "
        "    d.references_unattributed = ['An entry nobody could parse']",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    assert _node(graph, "has-text").assessment_state == "assessed_names_unresolved"


def test_the_assessment_axis_is_not_reported_below_the_third_tier(
    clean_graph, database
):
    """The floor the design section sets, asserted on a constructed state.

    Below tier 3 the tier already says the system has never read the document,
    so a second mark repeating it would be painted on almost every node while
    distinguishing none. The state below is not reachable through ingest — the
    PDF path writes an edition and the outcome together — so it is built here
    directly; the floor is a rule about what is reported, not about what
    ingest happens to produce.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'manifest-only'}) "
        "SET d.references_section_found = true, d.references_unattributed = []",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    node = _node(graph, "manifest-only")
    assert node.fidelity_tier == 2
    assert node.assessment_state is None
    assert node.unresolved_names is None


def test_an_external_neighbour_carries_the_lowest_tier_and_no_assessment(
    clean_graph, database
):
    """AE4: nothing about a cited-only neighbour may imply the system read it."""
    _seed_ladder(clean_graph, database)
    graph = build_graph(clean_graph, database, focus="hub")

    node = _node(graph, "cited-only")
    assert node.is_external is True
    assert node.fidelity_tier == 1
    assert node.assessment_state is None


def test_a_focused_response_counts_the_corpus_it_has_never_read(
    clean_graph, database
):
    """AE9: an empty set of citers is qualified, not presented as a finding.

    Four of the five corpus documents here have never had their references
    read, so none of them can appear as a citer of anything. Without that
    count the inbound half of a neighbourhood reads as 'nothing depends on
    this', which is the false all-clear R10 forbids.
    """
    _seed_ladder(clean_graph, database)
    graph = build_graph(clean_graph, database, focus="hub")

    assert graph.unread_corpus_documents == 4


def test_the_unread_count_falls_as_documents_are_read(clean_graph, database):
    """The count tracks the graph rather than being a constant.

    A parsed document whose section could not be located still cannot cite
    anything, so it stays counted; only a located section removes one.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-text'}) SET d.references_section_found = false",
        database_=database,
    )
    assert build_graph(clean_graph, database, focus="hub").unread_corpus_documents == 4

    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-text'}) SET d.references_section_found = true",
        database_=database,
    )
    assert build_graph(clean_graph, database, focus="hub").unread_corpus_documents == 3


def test_adding_the_fidelity_fields_changes_no_node_identity_or_count(
    clean_graph, database
):
    """The widened queries must report more about the same nodes, not more nodes.

    An OPTIONAL MATCH that multiplies rows is the ordinary way to get this
    wrong: a document with two editions and three obligations would arrive
    several times over, and a count-based assertion elsewhere would still pass.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (d:Document {slug: 'has-reviewed'}) "
        "MERGE (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: 'rev@2', "
        "  checksum: 'r2', source_uri: 'file:///r2.pdf'}) "
        "MERGE (v)-[:MANDATES]->(:Obligation {obligation_id: 'rev-2', "
        "  statement: 'Another duty.', modality: 'MUST', section_path: ['2']})",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    ids = [node.id for node in graph.nodes]
    assert sorted(ids) == [
        "cited-only",
        "has-obligations",
        "has-reviewed",
        "has-text",
        "hub",
        "manifest-only",
    ]
    assert len(ids) == len(set(ids))
    assert graph.returned_nodes == 6
    assert graph.total_nodes == 6
    assert _node(graph, "has-reviewed").fidelity_tier == 5


def test_the_corpus_wide_mode_reports_fidelity_too(clean_graph, database):
    """The older path is not left behind: both modes answer the same question."""
    _seed_ladder(clean_graph, database)
    graph = build_graph(clean_graph, database, include_external=True)

    assert _tiers(graph)["has-reviewed"] == 5
    assert _tiers(graph)["cited-only"] == 1
    assert graph.unread_corpus_documents == 4



def test_a_partly_resolved_section_reports_the_names_it_could_not_attribute(
    clean_graph, database
):
    """The precedence `_assessment`'s docstring calls the whole point, guarded.

    Every other fixture here puts unresolved names on a document with no
    outgoing references, so the two branches that precedence orders never both
    apply and swapping them changes nothing. A section that attributed some
    entries and failed on others is the ordinary partial parse, and it is the
    only state that tells the order apart: under the swap this document reports
    `assessed_all_resolved` and the gap it is still carrying disappears.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MATCH (t:Document {slug: 'has-text'}), (c:Document {slug: 'cited-only'}) "
        "MERGE (t)-[:REFERENCES]->(c) "
        "SET t.references_section_found = true, "
        "    t.references_unattributed = ['An entry nobody could parse']",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    node = _node(graph, "has-text")
    assert node.assessment_state == "assessed_names_unresolved"
    assert node.unresolved_names == ["An entry nobody could parse"]


def test_the_default_corpus_view_reports_fidelity_and_agrees_on_the_unread_count(
    clean_graph, database
):
    """The mode most requests hit, and the branch that derives the unread count.

    The corpus view computes the unread count from the rows it already holds
    while the focused view asks the database, so the number now has two
    derivations. That is only safe while they agree, and nothing else compares
    them: the rest of the suite exercises the corpus path with
    `include_external`, which is a different query.
    """
    _seed_ladder(clean_graph, database)
    graph = build_graph(clean_graph, database)

    assert "cited-only" not in {node.id for node in graph.nodes}
    assert _tiers(graph)["has-reviewed"] == 5
    assert _tiers(graph)["manifest-only"] == 2
    assert graph.unread_corpus_documents == 4
    assert (
        build_graph(clean_graph, database, focus="hub").unread_corpus_documents
        == graph.unread_corpus_documents
    ), "the derived count and the queried count have drifted apart"


def test_the_graph_endpoint_puts_fidelity_on_the_wire(client_with_auth):
    """The fields as a reader actually receives them, not as Python objects.

    Every other fidelity test calls `build_graph` directly, which cannot see a
    serialisation setting. `assessment_state` and `unresolved_names` are null
    for most of this corpus, and null has to arrive *present* — an
    `exclude_none` anywhere in the response path would drop the keys and the
    frontend type, which requires them, would be describing a shape the API
    does not send.
    """
    client_with_auth.post("/ingest", json={"filename": SAMPLE})
    body = client_with_auth.get("/graph").json()

    assert "unread_corpus_documents" in body
    node = next(n for n in body["nodes"] if n["id"] == "dodd-5000-01")
    assert node["fidelity_tier"] == 2
    assert "assessment_state" in node and node["assessment_state"] is None
    assert "unresolved_names" in node and node["unresolved_names"] is None


def test_a_document_reaches_the_top_tier_from_an_inbound_reviewed_link(
    clean_graph, database
):
    """The direction real review verdicts actually write.

    `replay_decisions` writes IMPLEMENTS source -> target between two different
    documents, so for every approved pair one document is the target — and the
    target only reaches the top tier because the match is undirected. Seeding
    only the source side, as the ladder fixture does, leaves that half of every
    real verdict untested: narrowing the match to `-[:IMPLEMENTS]->()` would
    keep the whole suite green while quietly demoting those documents from
    links-reviewed back to obligations-built.
    """
    _seed_ladder(clean_graph, database)
    clean_graph.execute_query(
        "MERGE (d:Document {slug: 'implemented-by-others', name: 'Implemented By Others'}) "
        "MERGE (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: 'ibo@1', "
        "  checksum: 'i', source_uri: 'file:///i.pdf'}) "
        "MERGE (v)-[:MANDATES]->(target:Obligation {obligation_id: 'ibo-1', "
        "  statement: 'The Component shall comply.', modality: 'MUST', section_path: ['1']}) "
        "WITH d, target "
        "MATCH (source:Obligation {obligation_id: 'rev-1'}) "
        "MERGE (source)-[:IMPLEMENTS]->(target) "
        "WITH d MATCH (hub:Document {slug: 'hub'}) MERGE (hub)-[:REFERENCES]->(d)",
        database_=database,
    )
    graph = build_graph(clean_graph, database, focus="hub")

    assert _node(graph, "implemented-by-others").fidelity_tier == 5
