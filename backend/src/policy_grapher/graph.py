"""Build the view of the graph the UI renders.

Corpus-first by default (ADR-002), with a deterministic render cap so a partial
view is always reported as partial.
"""

from neo4j import Driver, RoutingControl

from policy_grapher.models import GraphEdge, GraphNode, GraphOut


# The four signals R6's ladder is derived from, counted in the query that returns
# the node rather than fetched per node — the arrangement KTD1 requires, so no
# node costs a second round trip.
#
# An aggregating WITH is needed between *independent* branches off `d`, which is
# what `documents.DOCUMENT_FIELDS` has: without it two branches cross-multiply
# and the document arrives once per pair of rows. Three of the four signals here
# are not independent — an obligation belongs to an edition and a reviewed link
# belongs to an obligation — so they are one nested chain, walked once, and
# `count(DISTINCT …)` isolates each level from the fan-out below it. Restarting
# the chain from `d` for each count would re-walk HAS_VERSION three times and
# MANDATES twice to arrive at the same numbers.
#
# The reference count is a genuinely separate branch, so it keeps its own
# boundary. Its counts would survive being merged — DISTINCT would still be
# right — but the row set would become the product of the two fan-outs for
# nothing.
#
# `carry` is what the calling query must keep alive across those aggregations;
# everything not named in a WITH is dropped, which is why `degree` has to travel
# explicitly through every step for the queries that rank on it.
def _fidelity_fields(carry: str) -> str:
    return f"""
OPTIONAL MATCH (d)-[:HAS_VERSION]->(v:DocumentVersion)
OPTIONAL MATCH (v)-[:MANDATES]->(o:Obligation)
OPTIONAL MATCH (o)-[link:IMPLEMENTS]-()
WITH {carry}, count(DISTINCT v) AS editions,
     count(DISTINCT o) AS obligations, count(DISTINCT link) AS reviewed
OPTIONAL MATCH (d)-[:REFERENCES]->(out:Document)
WITH {carry}, editions, obligations, reviewed, count(DISTINCT out) AS resolved
"""


# Named once so the RETURN lists below cannot drift apart from each other.
_FIDELITY_RETURN = """
       editions, obligations, reviewed, resolved,
       d.references_section_found AS section_found,
       d.references_unattributed AS unattributed"""

CORPUS_NODES = (
    "MATCH (d:Document) WHERE NOT d:External"
    + _fidelity_fields("d")
    + """
RETURN d.slug AS id, d.name AS label, false AS is_external,"""
    + _FIDELITY_RETURN
    + """
ORDER BY d.slug ASC
"""
)

# Every row this query returns is external, and an external document is tier 1 by
# definition — `_fidelity_tier` short-circuits on `is_external` before reading any
# count, and `_assessment` reports nothing below the floor. Running the fidelity
# traversal here would walk HAS_VERSION, MANDATES and IMPLEMENTS for ~415 nodes to
# produce four numbers that are then discarded. The literals below say the same
# thing the WHERE clause already established, the way the corpus query states
# `false AS is_external` rather than reading the label back.
EXTERNAL_NODES_BY_DEGREE = (
    """
MATCH (d:Document) WHERE d:External
OPTIONAL MATCH (d)-[r:REFERENCES]-()
WITH d, count(r) AS degree,
     0 AS editions, 0 AS obligations, 0 AS reviewed, 0 AS resolved
RETURN d.slug AS id, d.name AS label, true AS is_external, degree,"""
    + _FIDELITY_RETURN
    + """
ORDER BY degree DESC, d.slug ASC
"""
)

# A corpus document whose references section has never been read may cite more
# than the graph shows: whatever outgoing edges it has came from a manifest row
# naming them, not from reading the document itself. So the inbound half of every
# neighbourhood is bounded by this number rather than by what the corpus actually
# says (AE9). Counted corpus-wide because that is the scope of the limitation.
#
# Note what this does not say. These documents are not silent — on the sample
# corpus every one of them is a live citer, drawn from its manifest row — so the
# caveat is that their citations are as complete as a manifest is, not that they
# have none.
UNREAD_CORPUS_DOCUMENTS = """
MATCH (d:Document)
WHERE NOT d:External AND NOT coalesce(d.references_section_found, false)
RETURN count(d) AS total
"""

EDGES_BETWEEN = """
MATCH (source:Document)-[:REFERENCES]->(target:Document)
WHERE source.slug IN $slugs AND target.slug IN $slugs
RETURN source.slug AS source, target.slug AS target
ORDER BY source ASC, target ASC
"""

DOCUMENT_EXISTS = "MATCH (d:Document {slug: $slug}) RETURN count(d) AS total"

FOCUS_NODE = (
    "MATCH (d:Document {slug: $slug})"
    + _fidelity_fields("d")
    + """
RETURN d.slug AS id, d.name AS label, d:External AS is_external,"""
    + _FIDELITY_RETURN
    + "\n"
)

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
NEIGHBOURS = (
    """
MATCH (source:Document)-[:REFERENCES]-(d:Document)
WHERE source.slug IN $slugs AND NOT d.slug IN $seen
WITH DISTINCT d
OPTIONAL MATCH (d)-[r:REFERENCES]-()
WITH d, count(r) AS degree"""
    + _fidelity_fields("d, degree")
    + """
RETURN d.slug AS id, d.name AS label, d:External AS is_external, degree,"""
    + _FIDELITY_RETURN
    + """
ORDER BY d.slug ASC
"""
)


# R6's five states, lowest to highest. Read as an ordinal: each rung says more
# has been done to the document than the rung below it.
TIER_CITED_ONLY = 1
TIER_IN_MANIFEST = 2
TIER_TEXT_INGESTED = 3
TIER_OBLIGATIONS_BUILT = 4
TIER_LINKS_REVIEWED = 5

# The assessment axis. `NOT_ASSESSED` deliberately covers both "parsed and no
# section found" and "never parsed": ingest keeps those apart because they are
# different facts about the parse, but to a reader of the map they are one
# statement — nothing has been read — and splitting them here would spend the
# map's scarcest channel on a distinction it cannot act on.
NOT_ASSESSED = "not_assessed"
ASSESSED_CITES_NOTHING = "assessed_cites_nothing"
ASSESSED_NAMES_UNRESOLVED = "assessed_names_unresolved"
ASSESSED_ALL_RESOLVED = "assessed_all_resolved"

# Below this the assessment state is not reported at all; see GraphNode.
ASSESSMENT_FLOOR = TIER_TEXT_INGESTED


def _fidelity_tier(
    *, is_external: bool, editions: int, obligations: int, reviewed: int
) -> int:
    """R6's ordinal, defined in one place so the ladder cannot drift.

    Tested from the top down, so the strongest evidence present decides. A
    document with reviewed links is at the top whatever the counts below it
    say, which keeps the ladder monotonic even against a graph in a state the
    ordinary pipeline would not produce.
    """
    if is_external:
        return TIER_CITED_ONLY
    if reviewed:
        return TIER_LINKS_REVIEWED
    if obligations:
        return TIER_OBLIGATIONS_BUILT
    if editions:
        return TIER_TEXT_INGESTED
    return TIER_IN_MANIFEST


def _assessment(
    *,
    tier: int,
    section_found: bool | None,
    unattributed: list[str] | None,
    resolved: int,
) -> tuple[str | None, list[str] | None]:
    """What the parser made of this document's own references section.

    The unresolved-names branch is tested before the "resolved nothing" one,
    and the order is the whole point. A document whose section was located but
    not one of whose entries could be attributed has resolved nothing — and it
    does not cite nothing. Reporting it as `ASSESSED_CITES_NOTHING` would state
    a finding about a document the parser demonstrably failed to read, which is
    the false all-clear ADR-015 exists to prevent. The design's own flowchart
    reads as if the count decides first; taken literally it produces exactly
    that output, so the branch that reports a gap wins.
    """
    if tier < ASSESSMENT_FLOOR:
        return None, None
    if not section_found:
        return NOT_ASSESSED, None
    names = list(unattributed or [])
    if names:
        return ASSESSED_NAMES_UNRESOLVED, names
    if resolved:
        return ASSESSED_ALL_RESOLVED, []
    return ASSESSED_CITES_NOTHING, []


def _node(record) -> GraphNode:
    """One row of any of the node queries above, rendered as a node.

    Every query returns the same fidelity columns, so this is the only place
    that has to know how a row becomes a node — and the only place a new field
    has to be added when the ladder grows.
    """
    tier = _fidelity_tier(
        is_external=record["is_external"],
        editions=record["editions"],
        obligations=record["obligations"],
        reviewed=record["reviewed"],
    )
    state, names = _assessment(
        tier=tier,
        section_found=record["section_found"],
        unattributed=record["unattributed"],
        resolved=record["resolved"],
    )
    return GraphNode(
        id=record["id"],
        label=record["label"],
        is_external=record["is_external"],
        fidelity_tier=tier,
        assessment_state=state,
        unresolved_names=names,
    )


class UnknownDocumentError(LookupError):
    """No document with the requested slug exists."""


def _unread_corpus_documents(driver: Driver, database: str) -> int:
    return _read(driver, database, UNREAD_CORPUS_DOCUMENTS)[0]["total"]


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

    focused = _node(origin[0])

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
            node = _node(record)
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
        unread_corpus_documents=_unread_corpus_documents(driver, database),
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

    # Kept as records, not just nodes: `CORPUS_NODES` already returns
    # `section_found` for every corpus document, which is exactly what the unread
    # count is a count of. Re-querying it would scan the corpus twice per request
    # on the default path to learn something already in hand.
    corpus_records = _read(driver, database, CORPUS_NODES)
    corpus = [_node(record) for record in corpus_records]

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

    external = [_node(record) for record in external_records]

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
        # Derived from the rows above rather than re-queried. `_focused_graph`
        # still asks the database, because it never fetches the whole corpus and
        # so has nothing to derive from.
        unread_corpus_documents=sum(
            1 for record in corpus_records if not record["section_found"]
        ),
    )
