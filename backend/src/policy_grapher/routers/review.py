"""The review queue: proposals awaiting a human verdict, and how one is recorded.

Two routes, both requiring a principal. `POST` writes an audit record, so the
actor comes from `require_principal` and from nowhere else.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.links.decisions import Verdict, record_decision, replay_decisions
from policy_grapher.models import ObligationCitationOut, ReviewItemOut, VerdictIn
from policy_grapher.obligations import primary_anchor

router = APIRouter(prefix="/review", tags=["review"])

# Proposals with no decision recorded against the same directed pair. The
# anti-join is on the two obligation ids rather than on the decision key, because
# the key is a hash computed in Python and Cypher cannot recompute it — which is
# exactly why `record_decision` stores both ids on the node alongside it.
# One citation per side. See `obligations.primary_anchor` for why an anchor is
# not matched directly. Substituted rather than formatted: the query already
# contains Cypher braces, which str.format would try to read as fields.
_QUEUE_TEMPLATE = """
MATCH (source:Obligation)-[r:IMPLEMENTS_PROPOSED]->(target:Obligation)
WHERE NOT EXISTS {
    MATCH (d:LinkDecision {source_obligation_id: source.obligation_id,
                           target_obligation_id: target.obligation_id})
}
--SOURCE-ANCHOR--
--TARGET-ANCHOR--
MATCH (source_doc:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(source)
MATCH (target_doc:Document)-[:HAS_VERSION]->(:DocumentVersion)-[:MANDATES]->(target)
RETURN source.obligation_id   AS source_id,
       source.statement       AS source_statement,
       source.modality        AS source_modality,
       source_doc.name        AS source_document,
       source_chunk.section_path AS source_section_path,
       source_chunk.page      AS source_page,
       target.obligation_id   AS target_id,
       target.statement       AS target_statement,
       target.modality        AS target_modality,
       target_doc.name        AS target_document,
       target_chunk.section_path AS target_section_path,
       target_chunk.page      AS target_page,
       r.confidence           AS confidence,
       r.rationale            AS rationale,
       r.proposer             AS proposer
ORDER BY r.confidence DESC, source_id, target_id
LIMIT $limit
"""

QUEUE = (
    _QUEUE_TEMPLATE
    .replace("--SOURCE-ANCHOR--", primary_anchor("source", "source_chunk"))
    .replace("--TARGET-ANCHOR--", primary_anchor("target", "target_chunk"))
)

PROPOSAL_EXISTS = """
MATCH (:Obligation {obligation_id: $source_id})
      -[:IMPLEMENTS_PROPOSED]->
      (:Obligation {obligation_id: $target_id})
RETURN count(*) AS total
"""


@router.get("/queue", response_model=list[ReviewItemOut])
def queue(
    limit: int = Query(default=50, ge=1, le=500),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> list[ReviewItemOut]:
    """Proposals nobody has decided yet, most confident first."""
    records, _, _ = driver.execute_query(
        QUEUE,
        {"limit": limit},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    return [
        ReviewItemOut(
            source=ObligationCitationOut(
                obligation_id=record["source_id"],
                statement=record["source_statement"],
                modality=record["source_modality"],
                document=record["source_document"],
                section_path=record["source_section_path"],
                page=record["source_page"],
            ),
            target=ObligationCitationOut(
                obligation_id=record["target_id"],
                statement=record["target_statement"],
                modality=record["target_modality"],
                document=record["target_document"],
                section_path=record["target_section_path"],
                page=record["target_page"],
            ),
            confidence=record["confidence"],
            rationale=record["rationale"],
            proposer=record["proposer"],
        )
        for record in records
    ]


@router.post("/{source_id}/{target_id}", response_model=dict[str, int])
def decide(
    source_id: str,
    target_id: str,
    body: VerdictIn,
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> dict[str, int]:
    """Record a verdict and apply it.

    `actor` is `principal.name`. The request body has no say in it.

    Recording and replaying happen in one transaction: a reviewer who approves a
    link expects it to be linked, and a decision that lands without its promotion
    would leave the graph disagreeing with the audit record until the next
    rebuild. `replay_decisions` is still the only writer of `IMPLEMENTS`.
    """
    if body.verdict not in set(Verdict):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown verdict {body.verdict!r}; expected one of "
                f"{[v.value for v in Verdict]}."
            ),
        )

    records, _, _ = driver.execute_query(
        PROPOSAL_EXISTS,
        {"source_id": source_id, "target_id": target_id},
        database_=settings.neo4j_database,
        routing_=RoutingControl.READ,
    )
    if records[0]["total"] == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No proposed link from {source_id!r} to {target_id!r}. A verdict "
                "is recorded against a proposal, not against an arbitrary pair."
            ),
        )

    def _write(tx):
        record_decision(
            tx,
            source_id=source_id,
            target_id=target_id,
            verdict=body.verdict,
            actor=principal.name,
            rationale=body.rationale,
        )
        return replay_decisions(tx)

    with driver.session(database=settings.neo4j_database) as session:
        return session.execute_write(_write)
