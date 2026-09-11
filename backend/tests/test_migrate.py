"""The startup migration: the legacy same-document :LinkDecision is converted,
retired, or both — and the edges it left behind go with it (spec, Migration).

Every fixture here that writes a :LinkDecision or an IMPLEMENTS_PROPOSED edge
between two editions of one document writes it raw, and that is the point of
this file: `record_decision` now refuses the pair and `propose_links` now skips
it, so the state these tests build can only exist as an inheritance from before
the split — which is exactly what a migration is for.
"""

import pytest
from fastapi.testclient import TestClient

from policy_grapher import main
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import (
    ExtractedObligation,
    Modality,
    obligation_id,
)
from policy_grapher.links.decisions import decision_key, replay_decisions
from policy_grapher.links.pairing import pairing_key, record_pairing
from policy_grapher.migrate import migrate_pairing_decisions
from policy_grapher.obligations import write_obligations

# Every statement says "shall" because `_seed_edition` labels them all SHALL and
# `ExtractedObligation` refuses a modality whose word is absent from the
# sentence it labels (extraction/schema.py) — the wording is otherwise arbitrary,
# and only has to differ per clause so the obligation ids differ.
OLD_WORDING = "The Director shall notify the Comptroller of any breach."
NEW_WORDING = (
    "The Director shall notify the Comptroller and the Secretary of any breach."
)
SECOND_OLD = "Components shall file the annual cybersecurity report."
SECOND_NEW = "Components shall file the annual cybersecurity report electronically."

ZEROS = {
    "converted": 0,
    "retired_same_edition": 0,
    "retired_conflicting": 0,
    "implements_deleted": 0,
    "proposals_deleted": 0,
}


def _seed_edition(
    driver, database, *, version_id, effective_date, statements, slug="doc", name="DOC"
):
    """One edition of one document, one obligation per statement, all in one
    section. Returns the obligation ids in statement order. `effective_date`
    pins the corpus ordering rule explicitly — the re-orientation tests must
    not be allowed to pass by accident of version_id lexicography."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $name}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf', effective_date: $eff})",
        {"slug": slug, "name": name, "vid": version_id, "eff": effective_date},
        database_=database,
    )
    chunk = chunk_pages(["1.1. DUTIES.\nBody.\n"], version_id=version_id)[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
        session.execute_write(
            write_obligations,
            version_id=version_id,
            chunk_id=chunk.chunk_id,
            section_path=chunk.section_path,
            obligations=[
                ExtractedObligation(
                    statement=s,
                    modality=Modality.SHALL,
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.9,
                )
                for s in statements
            ],
        )
    return [obligation_id(version_id, chunk.section_path, s) for s in statements]


def _legacy_decision(driver, database, *, source_id, target_id, verdict="approve"):
    """A :LinkDecision written raw, shaped exactly as RECORD_DECISION wrote it.

    Raw on purpose: `record_decision` now refuses a same-document pair, so the
    legacy state this migration exists for cannot be produced through the
    recorder any more. That refusal is the point; this helper is the
    archaeology."""
    driver.execute_query(
        "MERGE (d:LinkDecision {key: $key}) "
        "SET d.source_obligation_id = $source_id, "
        "    d.target_obligation_id = $target_id, "
        "    d.verdict = $verdict, "
        "    d.actor = 'walkthrough', "
        "    d.rationale = 'recorded before the split', "
        "    d.at = datetime()",
        {
            "key": decision_key(source_id, target_id),
            "source_id": source_id,
            "target_id": target_id,
            "verdict": verdict,
        },
        database_=database,
    )


def _replay(driver, database):
    with driver.session(database=database) as session:
        return session.execute_write(replay_decisions)


@pytest.mark.integration
def test_a_newer_to_older_approval_converts_re_oriented(clean_graph, database):
    """The walkthrough decision ran newer→older — its same-document proposal
    promoted that way. The diff's lookup is orientation-normalized, so a mutant
    migration that skips the swap passes any diff assertion; the observable
    that actually moves is the key. A mis-oriented node carries a key no
    pairings POST ever computes, so a reviewer re-verdicting the pair would
    MERGE a second decision beside it instead of replacing it. One pair, one
    node, one key.

    `record_pairing` is what the §6 POST calls and computes the same key, so
    driving it directly is the same observable; the POST's own ordering is
    pinned by `test_a_newer_first_post_is_recorded_older_to_newer`."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.verdict AS verdict, p.key AS key, "
        "p.actor AS actor, p.rationale AS rationale, p.at AS at",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["old"] == older_id
    assert records[0]["new"] == newer_id
    assert records[0]["verdict"] == "paired"
    assert records[0]["key"] == pairing_key(older_id, newer_id)
    assert records[0]["actor"] == "walkthrough"
    assert records[0]["rationale"] == "recorded before the split"
    assert records[0]["at"] is not None

    # The original survives its own conversion under the archival label, whole.
    # ADR-014 is what makes this an assertion rather than a detail: a migration
    # that took the live label off without putting the archival one on would
    # leave the verdict in an unlabelled node no query in this codebase names —
    # discarded in every sense but the storage engine's — and every assertion
    # above it would still pass.
    retired, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.key AS key, d.verdict AS verdict, d.actor AS actor, "
        "d.rationale AS rationale, d.source_obligation_id AS source, "
        "d.target_obligation_id AS target",
        database_=database,
    )
    assert len(retired) == 1
    assert retired[0]["reason"] == "converted"
    assert retired[0]["key"] == decision_key(newer_id, older_id)
    assert retired[0]["verdict"] == "approve"
    assert retired[0]["actor"] == "walkthrough"
    assert retired[0]["rationale"] == "recorded before the split"
    assert (retired[0]["source"], retired[0]["target"]) == (newer_id, older_id)

    # The replace observable: a re-verdict through the real write path must
    # land on the migrated node, not sit beside it.
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=older_id,
            new_id=newer_id,
            verdict="distinct",
            actor="tester",
            rationale="on reflection, a different duty",
        )
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total, "
        "collect(p.verdict) AS verdicts",
        database_=database,
    )
    assert records[0]["total"] == 1, "re-verdicting must replace, not accumulate"
    assert records[0]["verdicts"] == ["distinct"]


@pytest.mark.integration
def test_replay_recreates_no_same_document_implements_after_migration(
    clean_graph, database
):
    """`PROMOTE` has no document predicate, so a same-document approval left
    under the live label resurrects its edge on every review POST and every
    rebuild — into Ask's undirected traversal, which no shipped guard reaches.
    The migration must take the decision out of `PROMOTE`'s match by
    retirement, not delete around it."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)
    # The legacy promotion, through the one real writer of IMPLEMENTS.
    replayed = _replay(clean_graph, database)
    assert replayed["promoted"] == 1

    counts = migrate_pairing_decisions(clean_graph, database)
    assert counts["implements_deleted"] == 1

    after = _replay(clean_graph, database)

    assert after["promoted"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_shared_endpoint_approvals_retire_together(clean_graph, database):
    """Two convertible approvals sharing an endpoint within one edition pair
    would convert into exactly the two-live-`paired`-verdicts state the
    pairings POST's 409 exists to refuse — minted by a writer that route does
    not guard. Neither converts: a migration choosing the winner would be the
    design deciding what only a person may."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    newer_a, newer_b = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING, SECOND_NEW],
    )
    _legacy_decision(clean_graph, database, source_id=newer_a, target_id=older_id)
    _legacy_decision(clean_graph, database, source_id=newer_b, target_id=older_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 0
    assert counts["retired_conflicting"] == 2
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict ORDER BY d.key",
        database_=database,
    )
    assert [r["reason"] for r in records] == [
        "conflicting_pairing",
        "conflicting_pairing",
    ]
    assert [r["verdict"] for r in records] == ["approve", "approve"]
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_a_same_edition_approval_is_retired_with_its_edge_gone(clean_graph, database):
    """Reachable today — the rebuild API validates candidates by existence
    only, so a version can be named as its own candidate — and answering
    neither vocabulary's question: two clauses of one edition have no older or
    newer side to orient. Retired, never converted, every property intact
    (ADR-014 honoured in letter and spirit), the promoted edge deleted in the
    same transaction — and still gone after a replay, because the spec's
    Testing bullet asks for converted and same-edition finds alike to be taken
    out of `PROMOTE`'s match rather than deleted around."""
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    _legacy_decision(clean_graph, database, source_id=first, target_id=second)
    replayed = _replay(clean_graph, database)
    assert replayed["promoted"] == 1

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["retired_same_edition"] == 1
    assert counts["converted"] == 0
    assert counts["implements_deleted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict, d.actor AS actor, d.key AS key, "
        "d.source_obligation_id AS source, d.target_obligation_id AS target",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["reason"] == "same_edition"
    assert records[0]["verdict"] == "approve"
    assert records[0]["actor"] == "walkthrough"
    assert records[0]["key"] == decision_key(first, second)
    assert (records[0]["source"], records[0]["target"]) == (first, second)
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0

    # Deleting the edge is not enough. A node left under :LinkDecision with
    # verdict 'approve' is matched by PROMOTE on the next replay and the edge
    # comes straight back, so the retirement has to be observable through the
    # replay, not only through the edge count immediately after the migration.
    after = _replay(clean_graph, database)
    assert after["promoted"] == 0, (
        "a retired same-edition approval must be out of PROMOTE's match, not "
        "merely stripped of its edge"
    )
    records, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_same_document_proposals_are_deleted_and_cross_document_ones_kept(
    clean_graph, database
):
    """The review queue matches proposals with no document predicate, and the
    recorder's guard makes a same-document proposal undecidable — left in
    place it sits in the queue forever, inflating `pending`, unclearable by
    any verdict. Derived, so deleted. Scoped through one :Document: a
    cross-document proposal is live inventory and must survive."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    (other_id,) = _seed_edition(
        clean_graph, database, slug="other", name="OTHER",
        version_id="other@2020-01-01", effective_date="2020-01-01",
        statements=[SECOND_OLD],
    )
    # Raw for the same reason _legacy_decision is: propose_links now skips the
    # same-document pair. The cross-document edge is raw only for determinism,
    # carrying the same properties WRITE_PROPOSALS writes.
    for target in (older_id, other_id):
        clean_graph.execute_query(
            "MATCH (a:Obligation {obligation_id: $a}) "
            "MATCH (b:Obligation {obligation_id: $b}) "
            "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
            "proposer: 'lexical-v1'}]->(b)",
            {"a": newer_id, "b": target},
            database_=database,
        )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["proposals_deleted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    assert [(r["source"], r["target"]) for r in records] == [(newer_id, other_id)]


@pytest.mark.integration
def test_a_second_run_returns_all_zeros(clean_graph, database):
    """Idempotence is the vehicle's safety property: this runs on every boot.
    Everything the first run converts or retires stops matching the queries
    that found it, so the second run must report zeros across the board — a
    non-zero here means some node is still wearing the live label."""
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=first)
    _legacy_decision(clean_graph, database, source_id=first, target_id=second)
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $a}) "
        "MATCH (b:Obligation {obligation_id: $b}) "
        "MERGE (a)-[:IMPLEMENTS_PROPOSED {confidence: 0.9, rationale: 'legacy', "
        "proposer: 'lexical-v1'}]->(b)",
        {"a": newer_id, "b": first},
        database_=database,
    )

    initial = migrate_pairing_decisions(clean_graph, database)
    assert initial["converted"] == 1
    assert initial["retired_same_edition"] == 1
    assert initial["proposals_deleted"] == 1

    again = migrate_pairing_decisions(clean_graph, database)

    assert again == ZEROS


@pytest.mark.integration
def test_startup_runs_the_migration(client_with_graph):
    """The vehicle. A migration nobody schedules is a deletion that never
    happens; this one rides every boot, after apply_schema, because the
    conversion MERGEs against pairing_decision_key_unique. Idempotence (proved
    above) is what makes running it on every boot safe."""
    driver = client_with_graph.app.state.driver
    database = client_with_graph.app.state.settings.neo4j_database

    (older_id,) = _seed_edition(
        driver, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        driver, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(driver, database, source_id=newer_id, target_id=older_id)

    # A second lifespan against the same settings: the fixture's client booted
    # before the legacy decision existed, so a fresh boot must find and
    # convert it. The inner client's driver is its own and closes with it;
    # `driver` above belongs to the fixture's lifespan and stays open.
    with TestClient(main.app):
        pass

    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS live", database_=database
    )
    assert records[0]["live"] == 0
    records, _, _ = driver.execute_query(
        "MATCH (p:PairingDecision) RETURN p.verdict AS verdict", database_=database
    )
    assert [r["verdict"] for r in records] == ["paired"]
