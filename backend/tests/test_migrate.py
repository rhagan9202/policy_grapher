"""The startup migration: the legacy same-document :LinkDecision is converted,
retired, or both — and the edges it left behind go with it (spec, Migration).

Every fixture here that writes a :LinkDecision or an IMPLEMENTS_PROPOSED edge
between two editions of one document writes it raw, and that is the point of
this file: `record_decision` now refuses the pair and `propose_links` now skips
it, so the state these tests build can only exist as an inheritance from before
the split — which is exactly what a migration is for.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from policy_grapher import main
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.documents import delete_document
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
    "retired_unknown_verdict": 0,
    "retired_pairing_exists": 0,
    "implements_deleted": 0,
    "proposals_deleted": 0,
    "decisions_missing_documents": 0,
    "decisions_missing_obligations": 0,
}


def _seed_edition(
    driver,
    database,
    *,
    version_id,
    effective_date,
    statements,
    slug="doc",
    name="DOC",
    ingested_at=None,
):
    """One edition of one document, one obligation per statement, all in one
    section. Returns the obligation ids in statement order. `effective_date`
    pins the corpus ordering rule explicitly — the re-orientation tests must
    not be allowed to pass by accident of version_id lexicography.

    `effective_date=None` leaves the property unwritten rather than null,
    because that is what an undated edition looks like: setting a property to
    null in Cypher deletes it, so `versions.MERGE_VERSION` writing a null date
    and this writing none produce the same node. ADR-011 makes the date
    optional and `ingested_at` the designed fallback, so both legs of the
    ordering tuple need to be reachable from a fixture. `ingested_at` is
    stored as a real temporal, as `versions.py` stores it — a string would let
    the migration's `toString` pass by doing nothing."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $name}) "
        "MERGE (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: $vid}) "
        "SET v.checksum = $vid, v.source_uri = 'file:///d.pdf', "
        "    v.effective_date = $eff, "
        "    v.ingested_at = CASE WHEN $ingested IS NULL THEN NULL "
        "                         ELSE datetime($ingested) END",
        {
            "slug": slug,
            "name": name,
            "vid": version_id,
            "eff": effective_date,
            "ingested": ingested_at,
        },
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
    """A same-document approval left under the live label is matched by `PROMOTE`
    on every review POST and every rebuild. The migration must take the decision
    out of that match by *retirement*, not by deleting around it — a decision
    whose label survived its own conversion would resurrect the edge the
    conversion had just deleted.

    `PROMOTE` now screens the pair itself (links/decisions.py), which is why the
    legacy edge below is written raw rather than promoted into being: that screen
    is the first guard and this retirement the second, and the file's whole
    subject is a state the current writers can no longer produce."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)
    # The edge the legacy replay promoted, before `PROMOTE` screened documents.
    clean_graph.execute_query(
        "MATCH (source:Obligation {obligation_id: $source}) "
        "MATCH (target:Obligation {obligation_id: $target}) "
        "MERGE (source)-[:IMPLEMENTS]->(target)",
        {"source": newer_id, "target": older_id},
        database_=database,
    )
    assert _replay(clean_graph, database)["promoted"] == 0

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
    out of `PROMOTE`'s match rather than deleted around.

    The edge is written raw: both clauses belong to one edition of one document,
    so `PROMOTE`'s document predicate refuses to promote it now
    (links/decisions.py). An edge from before that screen existed is exactly what
    this migration inherits.
    """
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    _legacy_decision(clean_graph, database, source_id=first, target_id=second)
    clean_graph.execute_query(
        "MATCH (source:Obligation {obligation_id: $source}) "
        "MATCH (target:Obligation {obligation_id: $target}) "
        "MERGE (source)-[:IMPLEMENTS]->(target)",
        {"source": first, "target": second},
        database_=database,
    )
    assert _replay(clean_graph, database)["promoted"] == 0

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
def test_opposite_orientations_of_one_pair_retire_together(clean_graph, database):
    """Two legacy decisions on ONE pair, written in opposite directions, both
    re-orient to the same `(old, new)` and therefore compute the same key.
    `CONVERT` MERGEs on that key and SETs unconditionally, so without a screen
    the second row overwrites the first and one human's verdict replaces the
    other's — and `SAME_DOCUMENT_DECISIONS` has no ORDER BY, so *which* human
    wins is undefined, decided by whatever order the store returns rows in.

    Reachable in real legacy data: the pre-guard `propose_links` wrote
    proposals org→candidate, so rebuilding edition X against Y and later Y
    against X produced both directions, each independently reviewable.

    The endpoint rule cannot catch this pair — it counts endpoints only among
    candidates whose mapped verdict is `paired`, and the `reject` never enters
    that count. Duplicate *keys* are what must be detected, not shared
    endpoints: a legitimate `paired` on (X,Y) and `distinct` on (X,Z) inside
    one edition pair also share an endpoint and must still convert."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)
    _legacy_decision(
        clean_graph, database, source_id=older_id, target_id=newer_id,
        verdict="reject",
    )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 0
    assert counts["retired_conflicting"] == 2
    # Order-independent, and that is the point: whichever row the store
    # returned first, neither verdict may be silently replaced by the other.
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0, "a migration must not choose between two humans"
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict ORDER BY d.verdict",
        database_=database,
    )
    assert [r["reason"] for r in records] == [
        "conflicting_pairing",
        "conflicting_pairing",
    ]
    # Both verdicts survive under the archival label. Losing either is the bug.
    assert [r["verdict"] for r in records] == ["approve", "reject"]
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0

    assert migrate_pairing_decisions(clean_graph, database) == ZEROS


@pytest.mark.integration
def test_a_conversion_never_overwrites_an_existing_pairing_decision(
    clean_graph, database
):
    """`CONVERT`'s MERGE finds an existing `:PairingDecision` by key and its
    unconditional SET then replaces that decision's verdict, actor, rationale
    and timestamp with the legacy one's — destroying a verdict, silently and
    uncounted.

    Reachable without the pairings route: boot 1 converts a decision; a legacy
    decision boot 1 could not see — one obligation did not resolve, the class
    this migration deliberately leaves to `repoint_decisions` — is repointed
    onto live ids by a later rebuild; boot 2 converts it straight over the top.
    Here the victim is recorded through `record_pairing`, the real write path,
    because the verdict destroyed is not only a migrated one: any verdict a
    reviewer records through the product can be sitting on that key.

    The screen mirrors `repoint_decisions`, which faces the same problem and
    refuses the same way: a decision whose new key already belongs to another
    is left exactly as it was rather than merged over it."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=older_id,
            new_id=newer_id,
            verdict="paired",
            actor="alice",
            rationale="the same duty, reworded",
        )
    # Converts to the key alice's verdict already holds, with a verdict that
    # contradicts hers.
    _legacy_decision(
        clean_graph, database, source_id=newer_id, target_id=older_id,
        verdict="reject",
    )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["retired_pairing_exists"] == 1
    assert counts["converted"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.verdict AS verdict, p.actor AS actor, "
        "p.rationale AS rationale, p.key AS key",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["verdict"] == "paired", "alice's verdict must not be replaced"
    assert records[0]["actor"] == "alice"
    assert records[0]["rationale"] == "the same duty, reworded"
    assert records[0]["key"] == pairing_key(older_id, newer_id)
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["reason"] == "pairing_exists"
    # The legacy verdict is not converted, but neither is it discarded: it is
    # readable under the archival label, which is what a reviewer needs to
    # settle the disagreement by hand.
    assert records[0]["verdict"] == "reject"

    assert migrate_pairing_decisions(clean_graph, database) == ZEROS


@pytest.mark.integration
def test_two_paired_verdicts_on_one_clause_cannot_be_minted_across_two_runs(
    clean_graph, database
):
    """The conflict rule was enforced within a run only. Run 1 converting A→B
    and run 2 converting A→C leaves two live `paired` verdicts naming one
    clause in one edition pair — the state the pairings route's 409 exists to
    refuse (spec §6), minted by a writer that route does not guard, and
    reachable because a decision can arrive between two boots.

    The fix is that the endpoint rule reads the `:PairingDecision`s already in
    the graph as well as the candidates in this batch — a live `paired` verdict
    counts against its endpoints whichever run recorded it. The second clause's
    decision is not converted, so the pair stays for a person to settle."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    newer_a, newer_b = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING, SECOND_NEW],
    )
    _legacy_decision(clean_graph, database, source_id=newer_a, target_id=older_id)

    first = migrate_pairing_decisions(clean_graph, database)
    assert first["converted"] == 1

    # The decision that arrived between two boots.
    _legacy_decision(clean_graph, database, source_id=newer_b, target_id=older_id)

    second = migrate_pairing_decisions(clean_graph, database)

    assert second["converted"] == 0
    assert second["retired_conflicting"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision {verdict: 'paired'}) "
        "RETURN p.new_obligation_id AS new",
        database_=database,
    )
    assert [r["new"] for r in records] == [newer_a], (
        "one clause may hold one live `paired` verdict per edition pair, "
        "however many boots it takes to violate that"
    )


@pytest.mark.integration
def test_an_unrecognised_verdict_is_retired_rather_than_raised(clean_graph, database):
    """A verdict neither vocabulary knows is corruption, and the migration
    still has to finish. Raising would be the usual choice and is the wrong one
    here: this runs at every boot, so one corrupt node would make the
    application unstartable for everyone — including whoever needs it running
    to investigate, since there is no admin route, no screen and no export to
    reach from outside a process that will not start.

    It belongs with the other two unconvertible classes rather than in a
    category of its own that halts the run: the migration must work from
    whatever it finds, and anything it cannot map is retired, counted and
    reported instead of guessed at. Retiring is also strictly safer than
    leaving it — `PROMOTE` matches `approve` alone, so this verdict promotes
    nothing today, but the retirement puts it out of that match permanently and
    into a count a human can see."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(
        clean_graph, database, source_id=newer_id, target_id=older_id,
        verdict="maybe",
    )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["retired_unknown_verdict"] == 1
    assert counts["converted"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict, d.actor AS actor, d.rationale AS rationale, "
        "d.key AS key, d.source_obligation_id AS source, "
        "d.target_obligation_id AS target",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["reason"] == "unknown_verdict"
    # The unmappable value is kept verbatim, not normalised to something the
    # vocabulary does recognise: it is the only evidence of what went wrong.
    assert records[0]["verdict"] == "maybe"
    assert records[0]["actor"] == "walkthrough"
    assert records[0]["rationale"] == "recorded before the split"
    assert records[0]["key"] == decision_key(newer_id, older_id)
    assert (records[0]["source"], records[0]["target"]) == (newer_id, older_id)
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN count(p) AS total", database_=database
    )
    assert records[0]["total"] == 0, "an unmappable verdict must not be guessed at"
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0

    # Idempotent like the other two classes: the retired node stops matching
    # the read that found it, so the next boot reports nothing to do.
    assert migrate_pairing_decisions(clean_graph, database) == ZEROS


@pytest.mark.integration
def test_a_same_edition_decision_with_a_corrupt_verdict_reports_as_same_edition(
    clean_graph, database
):
    """Precedence between the two guards, which is otherwise invisible: both
    retire the node, so swapping the branches changes only which count reports
    it — and a refactor that reordered them would have nothing to fail.

    Same-edition wins because it is the stronger fact. That decision was never
    going to have its verdict mapped, whatever the verdict said, so reporting
    it as an unmappable verdict would claim a mapping was attempted and
    failed — and would hide a genuinely corrupt row in a count an operator
    reads as expected legacy."""
    first, second = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING, SECOND_OLD],
    )
    _legacy_decision(
        clean_graph, database, source_id=first, target_id=second, verdict="maybe",
    )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["retired_same_edition"] == 1
    assert counts["retired_unknown_verdict"] == 0
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason, "
        "d.verdict AS verdict",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["reason"] == "same_edition"
    assert records[0]["verdict"] == "maybe"


@pytest.mark.integration
def test_undated_editions_are_oriented_by_ingest_time(clean_graph, database):
    """The second leg of the ordering tuple, which no other fixture reaches:
    every other test here gives its editions distinct effective dates, and
    `_seed_edition` writes no `ingested_at` at all, so reducing the whole tuple
    to `effective_date` alone leaves them all green.

    ADR-011 makes the date optional and `ingested_at` the designed fallback, so
    an undated pair is not a hypothetical. Two things make this fixture bite
    where an obvious one would not:

    - The decision is written **older→newer**, so the correct answer is to
      leave the orientation alone. Written the other way round it would pass
      under a mutant that dropped the ordering entirely: two equal tuples take
      the `else` arm, which swaps — and swapping a newer→older decision is
      right by accident.
    - The version ids are chosen so lexical order *contradicts* ingest order
      (`zzz` ingested first), which kills an implementation that reached for
      the id before the timestamp."""
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@zzz", effective_date=None,
        ingested_at="2019-01-01T00:00:00Z", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@aaa", effective_date=None,
        ingested_at="2023-01-01T00:00:00Z", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=older_id, target_id=newer_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.key AS key",
        database_=database,
    )
    assert len(records) == 1
    assert (records[0]["old"], records[0]["new"]) == (older_id, newer_id)
    assert records[0]["key"] == pairing_key(older_id, newer_id)


@pytest.mark.integration
def test_editions_tied_on_date_and_ingest_time_are_oriented_by_version_id(
    clean_graph, database
):
    """The third leg — the tie-breaker this feature adds, and the one the
    pairing route's POST has to agree with, since two writers computing a directional key from
    two different orderings produce two nodes for one pair.

    Two undated editions ingested in one instant tie on the first two legs, and
    without the third neither orientation could be called older: the comparison
    would be equal, the `else` arm would take it, and the pair would be swapped
    whatever it said. The decision here is written older→newer, so swapping is
    exactly the wrong answer and an implementation missing this leg records the
    pair backwards."""
    same_instant = "2020-06-01T12:00:00Z"
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@aaa", effective_date=None,
        ingested_at=same_instant, statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@bbb", effective_date=None,
        ingested_at=same_instant, statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=older_id, target_id=newer_id)

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["converted"] == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.old_obligation_id AS old, "
        "p.new_obligation_id AS new, p.key AS key",
        database_=database,
    )
    assert len(records) == 1
    assert (records[0]["old"], records[0]["new"]) == (older_id, newer_id)
    assert records[0]["key"] == pairing_key(older_id, newer_id)


@pytest.mark.integration
def test_decisions_whose_obligations_lost_their_document_are_counted_not_touched(
    clean_graph, database
):
    """Every query here routes through `:Document`, so a decision whose
    obligations outlived their document is invisible to all of them — and stays
    under `:LinkDecision`, where `PROMOTE` resurrects its edge on every replay.
    A shipped route produces that state: `delete_document` removes the
    document, its versions and their chunks, and leaves the obligations behind.

    Counted and left alone, deliberately. Without documents there is no way to
    tell a same-document verdict from a cross-document one, and retiring a
    legitimate implements verdict would be this migration's own data loss. The
    real repair is deletion cascading to obligations, which is a different
    story. What this count buys is that the migration cannot report a graph
    clean when it knows there is part of it that it could not see."""
    (first_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (second_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=second_id, target_id=first_id)
    # Through the real route's function, not a hand-rolled delete: the point is
    # that shipped behaviour produces this state.
    delete_document(clean_graph, database, "doc")

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts["decisions_missing_documents"] == 1
    assert counts == {**ZEROS, "decisions_missing_documents": 1}
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.verdict AS verdict, "
        "d.retired_reason AS reason",
        database_=database,
    )
    assert len(records) == 1, "an unclassifiable decision must be left exactly as it is"
    assert records[0]["verdict"] == "approve"
    assert records[0]["reason"] is None
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0

    # A census, not a unit of work. The other counts go quiet once their work is
    # done; this one reports the same number every boot, because nothing here
    # repairs what it found. A census that quietly drifted would be worse than
    # one that never existed, so the second run is pinned rather than assumed.
    assert migrate_pairing_decisions(clean_graph, database) == {
        **ZEROS,
        "decisions_missing_documents": 1,
    }


@pytest.mark.integration
def test_a_decision_whose_obligation_is_gone_is_counted_not_reported_clean(
    clean_graph, database
):
    """The run that reported eight zeros over a graph it could not read.

    `SAME_DOCUMENT_DECISIONS` and `DECISIONS_MISSING_DOCUMENTS` both open by
    matching *both* obligations, so a decision missing one matched neither: not
    converted, not retired, and — until `decisions_missing_obligations` existed —
    not counted by the census whose own zero the other counts' completeness rests
    on. The operator was told the legacy state was clean while a same-document
    `approve` sat in the graph, waiting for a rebuild to reproduce the clause's
    content-derived id.

    Reproduced the way the state actually arises: the obligation node is deleted,
    which is what a re-extraction that moved the clause's section or wording
    leaves behind (ADR-027).
    """
    (older_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (newer_id,) = _seed_edition(
        clean_graph, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(clean_graph, database, source_id=newer_id, target_id=older_id)
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) DETACH DELETE o",
        {"id": older_id},
        database_=database,
    )

    counts = migrate_pairing_decisions(clean_graph, database)

    assert counts == {**ZEROS, "decisions_missing_obligations": 1}
    # Left exactly as it was, because `repoint_decisions` may still repair it and
    # retiring it here would destroy that repair.
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:LinkDecision) RETURN d.verdict AS verdict, "
        "d.retired_reason AS reason",
        database_=database,
    )
    assert len(records) == 1
    assert records[0]["verdict"] == "approve"
    assert records[0]["reason"] is None

    # And the edge it used to promote does not come back when the clause does:
    # re-creating the obligation under the same id is what a rebuild does, and
    # `PROMOTE`'s document predicate is what keeps the replay from minting a
    # same-document IMPLEMENTS in the window before the next boot converts it.
    _seed_edition(
        clean_graph, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    assert _replay(clean_graph, database)["promoted"] == 0
    edges, _, _ = clean_graph.execute_query(
        "MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS total", database_=database
    )
    assert edges[0]["total"] == 0
    # The next boot finds both obligations again and converts the verdict into
    # the pairing decision it always was, which is the repair this census points
    # an operator at.
    assert migrate_pairing_decisions(clean_graph, database) == {
        **ZEROS,
        "converted": 1,
    }


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


@pytest.mark.integration
def test_a_boot_survives_an_unrecognised_verdict(client_with_graph):
    """The blast radius, pinned at the vehicle rather than at the function.

    `lifespan` calls the migration, so anything the migration raises comes back
    out of `TestClient.__enter__` — which is why entering the context manager at
    all is this test's assertion, and why it errors rather than fails if the
    migration ever goes back to raising. One corrupt decision node must not cost
    everybody the application."""
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
    _legacy_decision(
        driver, database, source_id=newer_id, target_id=older_id, verdict="maybe",
    )

    with TestClient(main.app):
        pass

    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) RETURN count(d) AS live", database_=database
    )
    assert records[0]["live"] == 0
    records, _, _ = driver.execute_query(
        "MATCH (d:RetiredLinkDecision) RETURN d.retired_reason AS reason",
        database_=database,
    )
    assert [r["reason"] for r in records] == ["unknown_verdict"]


@pytest.mark.integration
def test_a_boot_warns_about_the_decisions_it_could_not_classify(
    client_with_graph, caplog
):
    """Ruling 2 is only worth anything if somebody reads it, and an operator
    reads a boot log rather than a docstring.

    Inside the INFO dict this count is one of eight, indistinguishable from the
    seven that report work done — and because it is a census rather than a
    repair it prints every boot forever and never clears, which teaches the
    reader to skip the line. So it gets its own record, at WARNING, carrying
    what the number means and what would repair it. This project has already
    shipped two counts that reached a caller and were rendered nowhere; a
    number nobody will read is the same as not reporting it."""
    driver = client_with_graph.app.state.driver
    database = client_with_graph.app.state.settings.neo4j_database

    (first_id,) = _seed_edition(
        driver, database, version_id="doc@2018-08-31",
        effective_date="2018-08-31", statements=[OLD_WORDING],
    )
    (second_id,) = _seed_edition(
        driver, database, version_id="doc@2022-07-28",
        effective_date="2022-07-28", statements=[NEW_WORDING],
    )
    _legacy_decision(driver, database, source_id=second_id, target_id=first_id)
    delete_document(driver, database, "doc")

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger="policy_grapher.main"),
        TestClient(main.app),
    ):
        pass

    warnings = [
        record
        for record in caplog.records
        if record.name == "policy_grapher.main"
        and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1, "the census needs a record of its own, not a dict key"
    message = warnings[0].getMessage()
    assert "1" in message
    # What the number means, and that the repair is somebody else's — both in
    # the line itself, because the docstring explaining it is not where an
    # operator is standing.
    assert "could not be classified" in message
    assert "no longer resolve to a document" in message
    assert "Nothing was changed" in message


@pytest.mark.integration
def test_a_boot_with_nothing_unclassifiable_logs_no_warning(
    client_with_graph, caplog
):
    """The other half, and the one that keeps the warning worth reading: a
    boot that found nothing it could not see must say nothing. A warning that
    fired unconditionally would be back to the noise the separate record exists
    to escape, and every assertion in the test above would still pass."""
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

    caplog.clear()
    with (
        caplog.at_level(logging.INFO, logger="policy_grapher.main"),
        TestClient(main.app),
    ):
        pass

    warnings = [
        record
        for record in caplog.records
        if record.name == "policy_grapher.main"
        and record.levelno == logging.WARNING
    ]
    assert warnings == []
    # The work-done counters still go out at INFO, unchanged: this boot really
    # did convert something, and that belongs in the dict rather than in a
    # warning.
    assert any(
        "Pairing decision migration" in record.getMessage()
        for record in caplog.records
        if record.name == "policy_grapher.main"
    )
