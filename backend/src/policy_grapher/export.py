"""A copy of the graph, taken before something destroys it — STORY-083.

The Reset screen has always said "there is no undo and no export", and it was
right. What Reset deletes is not uniformly expensive: chunks and obligations
cost hours of inference but are cached and repeatable (ADR-013), so a rebuild
reproduces them. A decision node is different. A reviewer's judgment is the only
thing here a machine cannot regenerate, and the confirm dialog already says a
rebuild replays decisions and cannot bring them back once they are gone.

Three labels carry that judgment now, not one: `:LinkDecision` for the
implements question, `:PairingDecision` for the pairing question, and
`:RetiredLinkDecision` for a decision the startup migration took out of the live
label without discarding. A category that names only some of them is a screen
promising a copy it does not take.

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
    # Property names are the ones `RECORD_DECISION` writes — `key`, `at`,
    # `rationale` (links/decisions.py). This query used to read `decision_key`
    # and `decided_at`, which nothing writes: every verdict recorded through
    # the real path exported with a null key and a null timestamp, and the
    # rationale was not exported at all. The verdict's value is actor,
    # rationale and timestamp; losing two of the three is losing the verdict.
    # `at` is a Cypher datetime; toString gives the ISO form so the route's
    # JSON encoder never meets a temporal type.
    #
    # Both labels, because a *retired* decision is still a human verdict Reset
    # destroys. The startup migration takes same-document decisions out of
    # `:LinkDecision` — relabelling them is how it stops `PROMOTE` resurrecting
    # their edges — so a query matching the live label alone exports one
    # decision before the first boot after the pairing split and none after it,
    # silently. Retirement is not deletion, and ADR-014 turns on the verdict
    # surviving somewhere a copy can reach.
    #
    # `retired_reason` is null for a live decision and says why for a retired
    # one. It is not decoration: the verdict alone stops explaining itself once
    # a decision can be retired for four different reasons, and whether a
    # judgement was converted, refused as ambiguous, or left to be settled by
    # hand is the part a reader restoring from this file would need.
    "decisions": """
        MATCH (decision:LinkDecision|RetiredLinkDecision)
        RETURN decision.key                  AS key,
               decision.source_obligation_id AS source_obligation_id,
               decision.target_obligation_id AS target_obligation_id,
               decision.verdict              AS verdict,
               decision.actor                AS actor,
               decision.rationale            AS rationale,
               decision.retired_reason       AS retired_reason,
               toString(decision.at)         AS at
        ORDER BY decision.key
    """,
    # The second canonical node, in its own category. `:PairingDecision`
    # answers the other question — whether a newer clause is the older one
    # reworded — and its properties say `old`/`new` rather than
    # `source`/`target` precisely because those names belong to the implements
    # question (links/pairing.py). Folding the two categories together would
    # lose which question a verdict answered, which is most of what it meant.
    "pairing_decisions": """
        MATCH (pairing:PairingDecision)
        RETURN pairing.key                 AS key,
               pairing.old_obligation_id   AS old_obligation_id,
               pairing.new_obligation_id   AS new_obligation_id,
               pairing.verdict             AS verdict,
               pairing.actor               AS actor,
               pairing.rationale           AS rationale,
               toString(pairing.at)        AS at
        ORDER BY pairing.key
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
