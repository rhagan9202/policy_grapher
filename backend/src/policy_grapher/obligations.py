"""Obligations in the graph — derived, like chunks, and droppable like them.

An obligation hangs off the version that mandates it and anchors to the chunk it
was read from, so a citation can quote the passage and name its page. Its id is
`hash(version_id, section_path, normalized_statement)` (extraction.schema), which
is stable across re-extraction — that is what lets Phase 4's human decisions
survive a rebuild instead of being orphaned by it.
"""

from neo4j import ManagedTransaction

from policy_grapher.extraction.schema import ExtractedObligation, obligation_id

WRITE_OBLIGATIONS = """
MATCH (v:DocumentVersion {version_id: $version_id})-[:HAS_CHUNK]->(c:Chunk {chunk_id: $chunk_id})
UNWIND $obligations AS o
MERGE (ob:Obligation {obligation_id: o.obligation_id})
SET ob.statement    = o.statement,
    ob.modality     = o.modality,
    ob.actor        = o.actor,
    ob.deadline     = o.deadline,
    ob.conditions   = o.conditions,
    ob.confidence   = o.confidence,
    ob.section_path = o.section_path
MERGE (v)-[:MANDATES]->(ob)
MERGE (ob)-[:ANCHORED_IN]->(c)
RETURN count(DISTINCT ob) AS written
"""

DROP_OBLIGATIONS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
DETACH DELETE o
"""


class UnknownAnchorError(Exception):
    """Raised when the version and chunk an obligation is written against do not
    name a version that holds that chunk.

    Without it the leading MATCH silently matches nothing: UNWIND never runs, no
    obligation is written, and a caller trusting the return value walks away
    believing it succeeded. The match deliberately requires the chunk to belong
    to *this* version — an obligation anchored in another edition's chunk would
    cite a passage the version does not contain.
    """


def write_obligations(
    tx: ManagedTransaction,
    *,
    version_id: str,
    chunk_id: str,
    section_path: list[str],
    obligations: list[ExtractedObligation],
) -> int:
    """Attach obligations read from one chunk. Returns how many distinct
    obligation nodes are now attached to it.

    The write is authoritative (`SET`, not `ON CREATE SET`). Identity normalises
    case and whitespace, so a re-extraction can reach an existing id carrying a
    different modality or confidence — and a store whose whole purpose is to say
    how binding a duty is must answer with the current reading, not the first one
    ever recorded.

    Raises UnknownAnchorError if no such version holds no such chunk.
    """
    if not obligations:
        return 0
    record = tx.run(
        WRITE_OBLIGATIONS,
        {
            "version_id": version_id,
            "chunk_id": chunk_id,
            "obligations": [
                {
                    "obligation_id": obligation_id(
                        version_id, section_path, o.statement
                    ),
                    "statement": o.statement,
                    "modality": str(o.modality),
                    "actor": o.actor,
                    "deadline": o.deadline,
                    "conditions": o.conditions,
                    "confidence": o.confidence,
                    "section_path": section_path,
                }
                for o in obligations
            ],
        },
    ).single()
    written = record["written"]
    if written == 0:
        raise UnknownAnchorError(
            f"no :DocumentVersion {version_id!r} holding chunk {chunk_id!r}; "
            "nothing was written"
        )
    return written


def drop_obligations(tx: ManagedTransaction, *, version_id: str) -> int:
    """Remove a version's obligations. Chunks and versions are untouched."""
    summary = tx.run(DROP_OBLIGATIONS, {"version_id": version_id}).consume()
    return summary.counters.nodes_deleted


def primary_anchor(obligation_var: str, chunk_var: str) -> str:
    """Cypher binding `chunk_var` to the one chunk that cites `obligation_var`.

    An obligation can legitimately anchor to more than one chunk: chunking
    overlaps text across a section split, so a sentence near a boundary is read
    out of both pieces — measured at 5 of 88 obligations on `500001p_2003.pdf`.
    A plain `MATCH (o)-[:ANCHORED_IN]->(c)` therefore multiplies rows, showing the
    same clause to a reviewer twice and inflating any count taken over it. Three
    separate queries hit this before it was worth naming; this is the shared fix.

    The earliest chunk in reading order is the citation, because that is where
    the passage starts.
    """
    return (
        f"CALL ({obligation_var}) {{\n"
        f"    MATCH ({obligation_var})-[:ANCHORED_IN]->(anchor:Chunk)\n"
        f"    RETURN anchor AS {chunk_var} ORDER BY anchor.ordinal LIMIT 1\n"
        f"}}"
    )
