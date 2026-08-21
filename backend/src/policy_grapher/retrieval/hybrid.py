"""Three signals, fused. Dropping any one of them makes this ordinary RAG.

**Lexical.** An exact designator — `DoDI 5000.88`, `s.14(2)` — is a lexical
object. Embeddings are poor at them: the vector for a document number carries
almost none of what makes that number the one you meant. A full-text index does
this perfectly and cheaply.

**Vector.** People ask in words the document does not use. "How do we protect
secret documents" has no term in common with "Personnel shall safeguard
classified material", and no keyword index will ever connect the two.

**Graph.** The leg that makes this *graph* retrieval rather than retrieval
standing next to a graph. Our own clause implementing a higher-level duty may
share no vocabulary with it at all — a question about a cybersecurity strategy
should still reach the calibration procedure someone approved as discharging it.
Nothing about the text connects those; a human-approved `IMPLEMENTS` edge does.
The traversal follows `IMPLEMENTS` and never `IMPLEMENTS_PROPOSED`, so an
unreviewed machine guess cannot pull a passage into an answer (ADR-014).

Fusion is reciprocal rank fusion. It needs no score calibration between legs,
which matters because a cosine similarity and a Lucene relevance score are not
denominated in the same thing and normalising them against each other would be
inventing a comparison.
"""

import re
from dataclasses import dataclass

from neo4j import Driver, RoutingControl

from policy_grapher.embedding import Embedder
from policy_grapher.embedding.schema import INDEX_NAME, check_identity

# Reciprocal rank fusion's damping term. 60 is the value from the original paper
# and the de facto default; named here rather than inlined so that a change to it
# is a visible decision. Larger flattens the contribution of rank; smaller makes
# the top hit of any one leg dominate.
RRF_K = 60

# Lucene's own operators. A query arriving from a search box is text, not syntax,
# and an unescaped `(` or `~` raises rather than returning nothing.
LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')

VECTOR_LEG = """
CALL db.index.vector.queryNodes($index, $k, $vector) YIELD node, score
RETURN node.chunk_id AS chunk_id
ORDER BY score DESC
"""

FULLTEXT_LEG = """
CALL db.index.fulltext.queryNodes($index, $query, {limit: $k}) YIELD node, score
RETURN node.chunk_id AS chunk_id
ORDER BY score DESC
"""

# Undirected on purpose: a question about a higher-level duty should reach the
# clause of ours that discharges it, and a question about ours should reach the
# duty it answers to. Both are the same edge read from opposite ends.
GRAPH_LEG = """
UNWIND $seed_ids AS seed_id
MATCH (:Chunk {chunk_id: seed_id})<-[:ANCHORED_IN]-(seed:Obligation)
MATCH (seed)-[:IMPLEMENTS]-(related:Obligation)
MATCH (related)-[:ANCHORED_IN]->(c:Chunk)
WHERE NOT c.chunk_id IN $seed_ids
RETURN DISTINCT seed_id, c.chunk_id AS chunk_id
"""

HYDRATE = """
UNWIND $chunk_ids AS chunk_id
MATCH (c:Chunk {chunk_id: chunk_id})
MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c)
MATCH (d:Document)-[:HAS_VERSION]->(v)
RETURN c.chunk_id     AS chunk_id,
       c.text         AS text,
       c.page         AS page,
       c.section_path AS section_path,
       d.name         AS document,
       d.slug         AS document_slug
"""

READ_INDEX_IDENTITY = """
MATCH (i:EmbeddingIndex {name: $name})
RETURN i.model_id AS model_id, i.dimensions AS dimensions
"""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    document: str
    document_slug: str
    section_path: list[str]
    page: int
    score: float
    signals: tuple[str, ...]


def escape_lucene(query: str) -> str:
    """Make an arbitrary string safe to hand a Lucene parser as terms."""
    return LUCENE_SPECIAL.sub(r"\\\1", query)


def _rank_contributions(ranked: list[str]) -> dict[str, float]:
    return {
        chunk_id: 1.0 / (RRF_K + rank)
        for rank, chunk_id in enumerate(ranked, start=1)
    }


def _vector_leg(
    driver: Driver, database: str, *, query: str, embedder: Embedder, k: int
) -> list[str]:
    if embedder.dimensions == 0:
        return []

    records, _, _ = driver.execute_query(
        READ_INDEX_IDENTITY,
        {"name": INDEX_NAME},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if not records:
        # Nothing has been embedded, so there is no index to search. Not an
        # error: the other two legs still answer.
        return []

    # Searching a model-A index with a model-B query vector is the same silent
    # failure as writing one, and gets the same refusal (ADR-016).
    check_identity(
        recorded_model=records[0]["model_id"],
        recorded_dimensions=records[0]["dimensions"],
        model_id=embedder.model_id,
        dimensions=embedder.dimensions,
    )

    vectors = embedder.embed([query])
    if not vectors:
        return []
    hits, _, _ = driver.execute_query(
        VECTOR_LEG,
        {"index": INDEX_NAME, "k": k, "vector": vectors[0]},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [record["chunk_id"] for record in hits]


def _fulltext_leg(driver: Driver, database: str, *, query: str, k: int) -> list[str]:
    escaped = escape_lucene(query).strip()
    if not escaped:
        return []
    hits, _, _ = driver.execute_query(
        FULLTEXT_LEG,
        {"index": "chunk_text", "query": escaped, "k": k},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [record["chunk_id"] for record in hits]


def _graph_leg(
    driver: Driver, database: str, *, seeds: list[str], seed_rank: dict[str, int]
) -> list[str]:
    """Expand from the seeds along approved links.

    A reached chunk inherits the rank of the best-ranked seed that found it, so
    an expansion from the top hit outranks one from the tail — the traversal is
    only as trustworthy as the passage it started from.
    """
    if not seeds:
        return []
    hits, _, _ = driver.execute_query(
        GRAPH_LEG,
        {"seed_ids": seeds},
        database_=database,
        routing_=RoutingControl.READ,
    )
    best: dict[str, int] = {}
    for record in hits:
        chunk_id = record["chunk_id"]
        rank = seed_rank.get(record["seed_id"], len(seed_rank) + 1)
        best[chunk_id] = min(best.get(chunk_id, rank), rank)
    return [chunk_id for chunk_id, _ in sorted(best.items(), key=lambda kv: (kv[1], kv[0]))]


def retrieve(
    driver: Driver,
    database: str,
    *,
    query: str,
    embedder: Embedder,
    limit: int = 10,
) -> list[RetrievedChunk]:
    """The passages most likely to answer `query`, most likely first.

    Every result carries its citation — document, section path, page — because a
    passage that cannot be quoted cannot ground an answer.
    """
    k = max(limit * 4, 20)
    legs = {
        "vector": _vector_leg(
            driver, database, query=query, embedder=embedder, k=k
        ),
        "fulltext": _fulltext_leg(driver, database, query=query, k=k),
    }

    seeds: list[str] = []
    for ranked in (legs["vector"], legs["fulltext"]):
        for chunk_id in ranked:
            if chunk_id not in seeds:
                seeds.append(chunk_id)
    legs["graph"] = _graph_leg(
        driver,
        database,
        seeds=seeds,
        seed_rank={chunk_id: rank for rank, chunk_id in enumerate(seeds, start=1)},
    )

    scores: dict[str, float] = {}
    signals: dict[str, list[str]] = {}
    for name, ranked in legs.items():
        for chunk_id, contribution in _rank_contributions(ranked).items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution
            signals.setdefault(chunk_id, []).append(name)

    if not scores:
        return []

    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
    records, _, _ = driver.execute_query(
        HYDRATE,
        {"chunk_ids": ordered},
        database_=database,
        routing_=RoutingControl.READ,
    )
    by_id = {record["chunk_id"]: record for record in records}

    return [
        RetrievedChunk(
            chunk_id=chunk_id,
            text=by_id[chunk_id]["text"],
            document=by_id[chunk_id]["document"],
            document_slug=by_id[chunk_id]["document_slug"],
            section_path=by_id[chunk_id]["section_path"],
            page=by_id[chunk_id]["page"],
            score=scores[chunk_id],
            signals=tuple(signals[chunk_id]),
        )
        for chunk_id in ordered
        if chunk_id in by_id
    ]
