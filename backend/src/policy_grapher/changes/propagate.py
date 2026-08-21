"""From a change to the policies that have to answer for it.

One traversal, no model. That is the point: every row is reachable by a path a
person can follow — this change, to this higher obligation, along an `IMPLEMENTS`
edge a named reviewer approved, to this clause of ours. Nothing here can invent an
obligation, and the reason a row appeared is the path itself.

The traversal names `IMPLEMENTS` and therefore cannot see `IMPLEMENTS_PROPOSED`.
That is the whole return on Phase 4's two edge types (ADR-014): an unreviewed
machine guess is unable to reach a compliance answer, by construction rather than
by a filter someone has to remember.
"""

from dataclasses import dataclass

from neo4j import ManagedTransaction

# Named, not inlined into the Cypher, because a policy analyst should be able to
# disagree with them. They are a starting position, not a measurement.
MODALITY_WEIGHT: dict[str, float] = {
    "SHALL": 4.0,
    "MUST": 4.0,
    "SHOULD": 2.0,
    "MAY": 1.0,
}

# REMOVED outranks MODIFIED because a policy of ours implementing something that
# no longer exists is a live compliance gap, whereas a reworded one is work.
KIND_WEIGHT: dict[str, float] = {
    "REMOVED": 3.0,
    "MODIFIED": 2.0,
    "ADDED": 1.0,
}

# A modality the schema does not allow cannot reach here (extraction.schema
# closes the enum), but a fallback keeps an unexpected value ranked lowest
# instead of raising in the middle of a triage run.
UNKNOWN_WEIGHT = 1.0

TRIAGE = """
MATCH (c:Change)-[:FROM_VERSION]->(:DocumentVersion {version_id: $from_version_id})
MATCH (c)-[:TO_VERSION]->(:DocumentVersion {version_id: $to_version_id})
MATCH (c)-[:AFFECTS]->(higher:Obligation)
MATCH (ours:Obligation)-[:IMPLEMENTS]->(higher)
// One citation per side. Chunk overlap repeats a sentence across a section split,
// so an obligation legitimately anchors to more than one chunk — 5 of 88 on a real
// DoD issuance. A plain MATCH would emit a row per combination, inflating the
// triage count and showing a reviewer the same clause twice. The earliest chunk in
// reading order is the citation: it is where the passage starts.
CALL (higher) {
    MATCH (higher)-[:ANCHORED_IN]->(chunk:Chunk)
    RETURN chunk AS higher_chunk ORDER BY chunk.ordinal LIMIT 1
}
CALL (ours) {
    MATCH (ours)-[:ANCHORED_IN]->(chunk:Chunk)
    RETURN chunk AS our_chunk ORDER BY chunk.ordinal LIMIT 1
}
MATCH (our_version:DocumentVersion)-[:MANDATES]->(ours)
MATCH (document:Document)-[:HAS_VERSION]->(our_version)
MATCH (higher_version:DocumentVersion)-[:MANDATES]->(higher)
MATCH (higher_document:Document)-[:HAS_VERSION]->(higher_version)
RETURN c.change_id          AS change_id,
       c.kind               AS kind,
       c.statement          AS higher_statement,
       c.previous_statement AS previous_statement,
       c.summary            AS summary,
       higher.modality      AS modality,
       higher.obligation_id AS higher_obligation_id,
       higher_chunk.section_path AS higher_section_path,
       higher_chunk.page    AS higher_page,
       higher_document.name AS higher_document,
       ours.obligation_id   AS our_obligation_id,
       ours.statement       AS our_statement,
       our_chunk.section_path AS our_section_path,
       our_chunk.page       AS our_page,
       document.name        AS document,
       document.slug        AS document_slug
"""

COUNT_CHANGES = """
MATCH (c:Change)-[:FROM_VERSION]->(:DocumentVersion {version_id: $from_version_id})
MATCH (c)-[:TO_VERSION]->(:DocumentVersion {version_id: $to_version_id})
MATCH (c)-[:AFFECTS]->(higher:Obligation)
RETURN count(DISTINCT c) AS total,
       count(DISTINCT CASE
           WHEN EXISTS { MATCH (:Obligation)-[:IMPLEMENTS]->(higher) } THEN c
       END) AS linked
"""


@dataclass(frozen=True)
class TriageRow:
    change_id: str
    kind: str
    score: float
    document: str
    document_slug: str
    our_obligation_id: str
    our_statement: str
    our_section_path: list[str]
    our_page: int
    higher_obligation_id: str
    higher_statement: str
    previous_statement: str | None
    higher_section_path: list[str]
    higher_page: int
    higher_document: str
    modality: str
    summary: str


@dataclass(frozen=True)
class TriageResult:
    rows: list[TriageRow]
    total_changes: int
    unlinked_changes: int


def score(kind: str, modality: str) -> float:
    """How urgently a change wants attention.

    Deliberately arithmetic over two named tables rather than anything learned:
    a reviewer who disagrees with an ordering can point at the number that caused
    it and argue about that number.

    The design sketched a third factor, tier distance — how far apart in the
    policy hierarchy the two documents sit. Nothing in the graph records a tier
    today, so it is not a factor here rather than being a factor silently fixed
    at 1.0. See ADR-015.
    """
    return KIND_WEIGHT.get(kind, UNKNOWN_WEIGHT) * MODALITY_WEIGHT.get(
        modality, UNKNOWN_WEIGHT
    )


def triage(
    tx: ManagedTransaction, *, from_version_id: str, to_version_id: str
) -> TriageResult:
    """Rank the org clauses a change between two editions reaches.

    Reports `unlinked_changes` alongside the rows. Without it an empty result is
    ambiguous in the worst possible direction: "nothing you own is affected" and
    "nothing has been reviewed yet, so this query cannot see anything" look
    identical, and one of them is a false all-clear.
    """
    rows = [
        TriageRow(
            change_id=record["change_id"],
            kind=record["kind"],
            score=score(record["kind"], record["modality"]),
            document=record["document"],
            document_slug=record["document_slug"],
            our_obligation_id=record["our_obligation_id"],
            our_statement=record["our_statement"],
            our_section_path=record["our_section_path"],
            our_page=record["our_page"],
            higher_obligation_id=record["higher_obligation_id"],
            higher_statement=record["higher_statement"],
            previous_statement=record["previous_statement"],
            higher_section_path=record["higher_section_path"],
            higher_page=record["higher_page"],
            higher_document=record["higher_document"],
            modality=record["modality"],
            summary=record["summary"],
        )
        for record in tx.run(
            TRIAGE,
            {"from_version_id": from_version_id, "to_version_id": to_version_id},
        )
    ]
    rows.sort(key=lambda row: (-row.score, row.document, row.our_obligation_id))

    counts = tx.run(
        COUNT_CHANGES,
        {"from_version_id": from_version_id, "to_version_id": to_version_id},
    ).single()
    return TriageResult(
        rows=rows,
        total_changes=counts["total"],
        unlinked_changes=counts["total"] - counts["linked"],
    )
