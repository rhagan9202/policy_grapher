"""A copy of the graph, taken before something destroys it — STORY-083.

The Reset screen has always said "there is no undo and no export", and it was
right. What Reset deletes is not uniformly expensive: chunks and obligations
cost hours of inference but are cached and repeatable (ADR-013), so a rebuild
reproduces them. `:LinkDecision` is different. A reviewer's judgment about
whether one clause implements another is the only thing here a machine cannot
regenerate, and the confirm dialog already says a rebuild replays decisions and
cannot bring them back once they are gone.

Export only. Restoring is a separate and larger problem: writing decisions back
means deciding what happens when the graph they refer to has moved underneath
them, which is the question ADR-027 had to answer carefully for rebuilds.
"""

from neo4j import Driver, RoutingControl

# One query per category, each returning the identifier the graph keys on so the
# file can be joined back together — and so an importer, if one is ever written,
# has something stable to match on rather than guessing from position.
QUERIES: dict[str, str] = {
    "documents": """
        MATCH (d:Document)
        RETURN d.slug AS slug,
               d.name AS name,
               'External' IN labels(d) AS is_external
        ORDER BY d.slug
    """,
    "versions": """
        MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)
        RETURN v.version_id     AS version_id,
               d.slug           AS slug,
               v.effective_date AS effective_date,
               v.checksum       AS checksum,
               v.source_uri     AS source_uri,
               v.build_state    AS build_state,
               v.build_counts   AS build_counts
        ORDER BY v.version_id
    """,
    "chunks": """
        MATCH (v:DocumentVersion)-[:HAS_CHUNK]->(c:Chunk)
        RETURN c.chunk_id     AS chunk_id,
               v.version_id   AS version_id,
               c.ordinal      AS ordinal,
               c.page         AS page,
               c.section_path AS section_path,
               c.text         AS text
        ORDER BY v.version_id, c.ordinal
    """,
    "obligations": """
        MATCH (v:DocumentVersion)-[:MANDATES]->(o:Obligation)
        RETURN o.obligation_id AS obligation_id,
               v.version_id    AS version_id,
               o.statement     AS statement,
               o.modality      AS modality,
               o.actor         AS actor,
               o.deadline      AS deadline,
               o.conditions    AS conditions,
               o.confidence    AS confidence,
               o.section_path  AS section_path
        ORDER BY o.obligation_id
    """,
    # Both edge kinds, with `promoted` saying which. A proposal and an approved
    # link are the same pair of ids in different states (ADR-014), and an export
    # that flattened them would lose the distinction Review exists to make.
    "proposals": """
        MATCH (source:Obligation)-[link:IMPLEMENTS|IMPLEMENTS_PROPOSED]->(target:Obligation)
        RETURN source.obligation_id AS source_obligation_id,
               target.obligation_id AS target_obligation_id,
               type(link) = 'IMPLEMENTS' AS promoted,
               link.proposer AS proposer,
               link.score    AS score
        ORDER BY source.obligation_id, target.obligation_id
    """,
    "decisions": """
        MATCH (decision:LinkDecision)
        RETURN decision.decision_key         AS decision_key,
               decision.source_obligation_id AS source_obligation_id,
               decision.target_obligation_id AS target_obligation_id,
               decision.verdict              AS verdict,
               decision.actor                AS actor,
               decision.decided_at           AS decided_at
        ORDER BY decision.decision_key
    """,
    "changes": """
        MATCH (change:Change)
        OPTIONAL MATCH (change)-[:FROM_VERSION]->(from:DocumentVersion)
        OPTIONAL MATCH (change)-[:TO_VERSION]->(to:DocumentVersion)
        RETURN change.change_id      AS change_id,
               change.kind           AS kind,
               from.version_id       AS from_version_id,
               to.version_id         AS to_version_id
        ORDER BY change.change_id
    """,
}


def export_graph(driver: Driver, database: str) -> dict[str, list[dict]]:
    """Every category Reset names as deleted, keyed by category name.

    A dict of lists rather than a stream of typed records: a reader opening the
    file finds a category by name without consulting this module.
    """
    exported: dict[str, list[dict]] = {}
    for category, query in QUERIES.items():
        records, _, _ = driver.execute_query(
            query, database_=database, routing_=RoutingControl.READ
        )
        exported[category] = [dict(record) for record in records]
    return exported
