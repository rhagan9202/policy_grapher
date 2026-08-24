"""The question the increment exists to answer.

*A higher-level policy changed; which of our policies are affected, and how
urgently?* The answer is a diff and a traversal — no model on this path, so every
row is explained by the path that produced it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver, RoutingControl

from policy_grapher.auth import Principal, require_principal
from policy_grapher.changes.diff import diff_versions
from policy_grapher.changes.propagate import triage as run_triage
from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings, get_driver
from policy_grapher.models import TriageCitationOut, TriageOut, TriageRowOut

router = APIRouter(prefix="/triage", tags=["triage"])

VERSION_EXISTS = """
MATCH (v:DocumentVersion {version_id: $version_id}) RETURN count(v) AS total
"""

PREDECESSOR = """
MATCH (:DocumentVersion {version_id: $version_id})-[:SUPERSEDES]->(older:DocumentVersion)
RETURN older.version_id AS version_id
"""

COUNT_OBLIGATIONS = """
MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation)
RETURN count(o) AS obligations
"""


def _require_version(driver: Driver, database: str, version_id: str) -> None:
    records, _, _ = driver.execute_query(
        VERSION_EXISTS,
        {"version_id": version_id},
        database_=database,
        routing_=RoutingControl.READ,
    )
    if records[0]["total"] == 0:
        raise HTTPException(
            status_code=404, detail=f"No edition with version_id {version_id!r}."
        )


@router.get("", response_model=TriageOut)
def read_triage(
    to_version_id: str = Query(...),
    from_version_id: str | None = Query(default=None),
    driver: Driver = Depends(get_driver),
    settings: Settings = Depends(get_app_settings),
    principal: Principal = Depends(require_principal),
) -> TriageOut:
    """Which of our clauses a change between two editions reaches, ranked.

    An unknown edition is a 404 rather than an empty result. An empty result
    reads as "nothing is affected", which is the one answer this tool must never
    give by accident — and a mistyped version id would otherwise produce exactly
    that, indistinguishable from a real all-clear.

    Omitting `from_version_id` compares against the edition this one supersedes
    (ADR-011's derived chain). The resolved value is echoed in the response.

    The diff runs here rather than behind a separate write endpoint: it is
    deterministic and drops-then-writes its own version pair, so repeating this
    request converges on the same `:Change` set rather than accumulating. The
    trade is that a GET writes derived nodes — see ADR-015.
    """
    database = settings.neo4j_database
    _require_version(driver, database, to_version_id)

    if from_version_id is None:
        records, _, _ = driver.execute_query(
            PREDECESSOR,
            {"version_id": to_version_id},
            database_=database,
            routing_=RoutingControl.READ,
        )
        if not records:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{to_version_id!r} supersedes no earlier edition, so there is "
                    "nothing to compare it against. Pass from_version_id explicitly."
                ),
            )
        from_version_id = records[0]["version_id"]
    else:
        _require_version(driver, database, from_version_id)

    resolved_from = from_version_id

    def _work(tx):
        diff_versions(
            tx, from_version_id=resolved_from, to_version_id=to_version_id
        )
        result = run_triage(
            tx, from_version_id=resolved_from, to_version_id=to_version_id
        )
        # Read inside the same transaction as the diff and the triage, so the
        # count reflects the same graph state those two just read — not a
        # separate read that could race a concurrent rebuild.
        from_obligations = tx.run(
            COUNT_OBLIGATIONS, {"version_id": resolved_from}
        ).single()["obligations"]
        to_obligations = tx.run(
            COUNT_OBLIGATIONS, {"version_id": to_version_id}
        ).single()["obligations"]
        return result, from_obligations, to_obligations

    with driver.session(database=database) as session:
        result, from_obligations, to_obligations = session.execute_write(_work)

    return TriageOut(
        from_version_id=resolved_from,
        to_version_id=to_version_id,
        total_changes=result.total_changes,
        unlinked_changes=result.unlinked_changes,
        from_obligations=from_obligations,
        to_obligations=to_obligations,
        rows=[
            TriageRowOut(
                change_id=row.change_id,
                kind=row.kind,
                score=row.score,
                modality=row.modality,
                summary=row.summary,
                previous_statement=row.previous_statement,
                ours=TriageCitationOut(
                    obligation_id=row.our_obligation_id,
                    statement=row.our_statement,
                    document=row.document,
                    section_path=row.our_section_path,
                    page=row.our_page,
                ),
                higher=TriageCitationOut(
                    obligation_id=row.higher_obligation_id,
                    statement=row.higher_statement,
                    document=row.higher_document,
                    section_path=row.higher_section_path,
                    page=row.higher_page,
                ),
            )
            for row in result.rows
        ],
    )
