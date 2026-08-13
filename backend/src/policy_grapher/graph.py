"""Build the view of the graph the UI renders.

Corpus-first by default (ADR-002), with a deterministic render cap so a partial
view is always reported as partial.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import GraphEdge, GraphNode, GraphOut

CORPUS_NODES = """
MATCH (d:Document) WHERE NOT d:External
RETURN d.slug AS id, d.name AS label, d.reference_role AS reference_role
ORDER BY d.slug ASC
"""

EXTERNAL_NODES_BY_DEGREE = """
MATCH (d:Document) WHERE d:External
OPTIONAL MATCH (d)-[r:REFERENCES]-()
WITH d, count(r) AS degree
RETURN d.slug AS id, d.name AS label, degree
ORDER BY degree DESC, d.slug ASC
"""

EXTERNAL_NEIGHBOURS = """
MATCH (source:Document {slug: $slug})-[:REFERENCES]-(d:Document)
WHERE d:External
WITH DISTINCT d
OPTIONAL MATCH (d)-[r:REFERENCES]-()
RETURN d.slug AS id, d.name AS label, count(r) AS degree
ORDER BY degree DESC, d.slug ASC
"""

EDGES_BETWEEN = """
MATCH (source:Document)-[:REFERENCES]->(target:Document)
WHERE source.slug IN $slugs AND target.slug IN $slugs
RETURN source.slug AS source, target.slug AS target
ORDER BY source ASC, target ASC
"""

DOCUMENT_EXISTS = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"


class UnknownDocumentError(LookupError):
    """No document with the requested slug exists."""


def _read(driver: Driver, database: str, cypher: str, params: dict | None = None):
    records, _, _ = driver.execute_query(
        cypher, params or {}, database_=database, routing_=RoutingControl.READ
    )
    return records


def build_graph(
    driver: Driver,
    database: str,
    *,
    include_external: bool = False,
    expand: str | None = None,
    limit: int | None = None,
) -> GraphOut:
    corpus = [
        GraphNode(
            id=record["id"],
            label=record["label"],
            reference_role=record["reference_role"],
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
        external_records = _read(driver, database, EXTERNAL_NEIGHBOURS, {"slug": expand})
    else:
        external_records = []

    external = [
        GraphNode(
            id=record["id"],
            label=record["label"],
            reference_role=None,
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

    return GraphOut(
        nodes=nodes,
        edges=edges,
        total_nodes=total_nodes,
        returned_nodes=len(nodes),
        truncated=len(nodes) < total_nodes,
    )
