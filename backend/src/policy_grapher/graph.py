"""Build the view of the graph the UI renders.

Corpus-first by default (ADR-002), with a deterministic render cap so a partial
view is always reported as partial.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import GraphEdge, GraphNode, GraphOut

CORPUS_NODES = """
MATCH (d:Document) WHERE NOT d:External
RETURN d.slug AS id, d.name AS label
ORDER BY d.slug ASC
"""

EXTERNAL_NODES_BY_DEGREE = """
MATCH (d:Document) WHERE d:External
OPTIONAL MATCH (d)-[r:REFERENCES]-()
WITH d, count(r) AS degree
RETURN d.slug AS id, d.name AS label, degree
ORDER BY degree DESC, d.slug ASC
"""

EDGES_BETWEEN = """
MATCH (source:Document)-[:REFERENCES]->(target:Document)
WHERE source.slug IN $slugs AND target.slug IN $slugs
RETURN source.slug AS source, target.slug AS target
ORDER BY source ASC, target ASC
"""

DOCUMENT_EXISTS = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"

FOCUS_NODE = """
MATCH (d:Document {slug: $slug})
RETURN d.slug AS id, d.name AS label, d:External AS is_external
"""

# One degree out from everything named, in either direction: what these
# documents cite and what cites them.
#
# Called once per degree rather than with a variable-length pattern, because the
# depth bound in `[:REFERENCES*1..n]` must be a literal — and building that
# literal from a request parameter would be authoring Cypher from input, which
# ADR-017 forbids. Depth is small by design (R5 expands one degree at a time),
# so the extra round trips are cheap and the query stays a constant.
#
# This is also the query the `expand` mode uses, called with a single slug and
# an empty exclusion set. It replaced a near-identical `EXTERNAL_NEIGHBOURS`
# that differed only in filtering to externals inside Cypher rather than
# returning the flag. Keeping both meant maintaining one traversal twice: the
# degree-doubling bug `test_expand_ranks_external_neighbours_by_true_degree`
# exists for had already been fixed in each copy separately, with nothing
# marking them as the same query.
NEIGHBOURS = """
MATCH (source:Document)-[:REFERENCES]-(d:Document)
WHERE source.slug IN $slugs AND NOT d.slug IN $seen
WITH DISTINCT d
OPTIONAL MATCH (d)-[r:REFERENCES]-()
RETURN d.slug AS id, d.name AS label, d:External AS is_external, count(r) AS degree
ORDER BY d.slug ASC
"""


class UnknownDocumentError(LookupError):
    """No document with the requested slug exists."""


def _read(driver: Driver, database: str, cypher: str, params: dict | None = None):
    records, _, _ = driver.execute_query(
        cypher, params or {}, database_=database, routing_=RoutingControl.READ
    )
    return records


TRUNCATION_BASIS = (
    "the focused document first, then the documents the corpus holds, "
    "then external references by how often they are cited"
)

# The corpus-wide mode's own order, which is a different rule: every corpus
# document survives and the cap is spent entirely on externals.
CORPUS_TRUNCATION_BASIS = (
    "every document the corpus holds, then external references by how often "
    "they are cited"
)


def _focused_graph(
    driver: Driver,
    database: str,
    *,
    focus: str,
    depth: int,
    limit: int | None,
) -> GraphOut:
    """One document and its dependency neighbourhood, and nothing else.

    The budget is spent *inside* the neighbourhood. An earlier draft of this
    allocated the focused document and its neighbours first and then let the rest
    of the corpus fill whatever remained, which reads as a sensible priority
    order and is not: this corpus holds 23 documents against a render cap of 300,
    so that second tier always fits whole and the focused view would render as
    the corpus view with extra steps. Documents outside the neighbourhood are not
    ranked lower here — they are not admitted.
    """
    origin = _read(driver, database, FOCUS_NODE, {"slug": focus})
    if not origin:
        raise UnknownDocumentError(focus)

    focused = GraphNode(
        id=origin[0]["id"],
        label=origin[0]["label"],
        is_external=origin[0]["is_external"],
    )

    corpus_neighbours: list[GraphNode] = []
    external_neighbours: list[tuple[int, str, GraphNode]] = []
    seen = {focused.id}
    frontier = [focused.id]

    for _ in range(max(1, depth)):
        if not frontier:
            break
        records = _read(
            driver, database, NEIGHBOURS, {"slugs": frontier, "seen": sorted(seen)}
        )
        frontier = []
        for record in records:
            node = GraphNode(
                id=record["id"],
                label=record["label"],
                is_external=record["is_external"],
            )
            seen.add(node.id)
            frontier.append(node.id)
            if node.is_external:
                external_neighbours.append((-record["degree"], node.id, node))
            else:
                corpus_neighbours.append(node)

    corpus_neighbours.sort(key=lambda node: node.id)
    external_neighbours.sort(key=lambda entry: (entry[0], entry[1]))
    ordered = [focused, *corpus_neighbours, *(entry[2] for entry in external_neighbours)]

    total_nodes = len(ordered)
    # The focused document survives any budget. A view that dropped the thing it
    # is a view of would answer a question nobody asked.
    kept = ordered[: max(1, limit)] if limit is not None and limit > 0 else ordered

    slugs = [node.id for node in kept]
    edges = [
        GraphEdge(source=record["source"], target=record["target"])
        for record in _read(driver, database, EDGES_BETWEEN, {"slugs": slugs})
    ]
    truncated = len(kept) < total_nodes

    return GraphOut(
        nodes=kept,
        edges=edges,
        total_nodes=total_nodes,
        returned_nodes=len(kept),
        truncated=truncated,
        truncation_basis=TRUNCATION_BASIS if truncated else None,
    )


def build_graph(
    driver: Driver,
    database: str,
    *,
    include_external: bool = False,
    expand: str | None = None,
    limit: int | None = None,
    focus: str | None = None,
    depth: int = 1,
) -> GraphOut:
    # The focused neighbourhood is a different question from the corpus view, not
    # a filter on it, so it answers before the corpus is read at all. The
    # corpus-wide mode below stays reachable: this changes which mode is primary,
    # not which modes exist.
    if focus:
        return _focused_graph(
            driver, database, focus=focus, depth=depth, limit=limit
        )

    corpus = [
        GraphNode(
            id=record["id"],
            label=record["label"],
            is_external=False,
        )
        for record in _read(driver, database, CORPUS_NODES)
    ]

    if expand:
        exists = _read(driver, database, DOCUMENT_EXISTS, {"slug": expand})
        if exists[0]["total"] == 0:
            raise UnknownDocumentError(expand)

    if include_external:
        external_records = _read(driver, database, EXTERNAL_NODES_BY_DEGREE)
    elif expand:
        # The same one-hop traversal the focused mode walks, called with a single
        # slug and nothing excluded, then filtered to the externals this mode
        # admits. `NEIGHBOURS` orders by slug because the focused mode re-sorts
        # in Python; this mode's degree ordering is applied here instead.
        external_records = sorted(
            (
                record
                for record in _read(
                    driver, database, NEIGHBOURS, {"slugs": [expand], "seen": []}
                )
                if record["is_external"]
            ),
            key=lambda record: (-record["degree"], record["id"]),
        )
    else:
        external_records = []

    external = [
        GraphNode(
            id=record["id"],
            label=record["label"],
            is_external=True,
        )
        for record in external_records
    ]

    total_nodes = len(corpus) + len(external)

    # Corpus documents always survive; the cap eats into externals only.
    if limit is not None and limit > 0:
        budget = max(0, limit - len(corpus))
        kept_external = external[:budget]
    else:
        kept_external = external

    nodes = corpus + kept_external
    slugs = [node.id for node in nodes]
    edges = [
        GraphEdge(source=record["source"], target=record["target"])
        for record in _read(driver, database, EDGES_BETWEEN, {"slugs": slugs})
    ]

    truncated = len(nodes) < total_nodes

    return GraphOut(
        nodes=nodes,
        edges=edges,
        total_nodes=total_nodes,
        returned_nodes=len(nodes),
        truncated=truncated,
        # This branch truncates in production — `include_external` past the cap
        # does it on the sample corpus today — and said nothing about why until
        # now. A null basis is defined on the field as "nothing was dropped", so
        # leaving it unset here asserted completeness on a response that had just
        # dropped 138 nodes. That is the same misleading emptiness the focused
        # mode's basis exists to prevent, on the older path.
        truncation_basis=CORPUS_TRUNCATION_BASIS if truncated else None,
    )
