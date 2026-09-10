"""Diffing two editions of one instrument into changes a reviewer can read."""

import pytest

from policy_grapher.changes.diff import (
    ADDED,
    MODIFIED,
    REMOVED,
    _plan_changes,
    content_key,
    diff_versions,
    drop_candidates,
    drop_changes,
)
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.links.propose import Candidate, score_pair, score_pairing
from policy_grapher.obligations import write_obligations

# --- the key the diff matches on ---------------------------------------------


def test_the_content_key_ignores_the_edition():
    """An obligation_id hashes its version, so the same clause in two editions has
    two ids. The diff has to match on what is left when the edition is removed,
    or every obligation in the document reads as removed-and-re-added."""
    assert content_key(["3.2"], "The Director shall notify.") == content_key(
        ["3.2"], "The Director shall notify."
    )


def test_the_content_key_ignores_whitespace_and_case():
    """Matched the way identity is matched: a reflow is not a change."""
    assert content_key(["3.2"], "The Director shall notify.") == content_key(
        ["3.2"], "the  DIRECTOR   shall\nnotify."
    )


def test_the_content_key_distinguishes_sections():
    assert content_key(["3.2"], "Same words.") != content_key(["4.1"], "Same words.")


def test_the_content_key_distinguishes_wording():
    assert content_key(["3.2"], "Notify the Comptroller.") != content_key(
        ["3.2"], "Notify the Secretary."
    )


# --- seeding ------------------------------------------------------------------


def _seed(driver, database, *, version_id, entries):
    """`entries` is (section, statement, modality) triples."""
    driver.execute_query(
        "MERGE (d:Document {slug: 'doc', name: 'DOC'}) "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"vid": version_id},
        database_=database,
    )
    by_section: dict[str, list[tuple[str, Modality]]] = {}
    for section, statement, modality in entries:
        by_section.setdefault(section, []).append((statement, modality))

    with driver.session(database=database) as session:
        for section, items in by_section.items():
            chunk = chunk_pages(
                [f"{section}. TITLE.\nBody text.\n"], version_id=version_id
            )[-1]
            assert chunk.section_path == [section], chunk.section_path
            session.execute_write(write_chunks, version_id=version_id, chunks=[chunk])
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=modality,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                    for statement, modality in items
                ],
            )


def _diff(driver, database, *, old="v1", new="v2"):
    with driver.session(database=database) as session:
        return session.execute_write(
            diff_versions, from_version_id=old, to_version_id=new
        )


def _changes(driver, database):
    records, _, _ = driver.execute_query(
        "MATCH (c:Change) RETURN c.kind AS kind, c.section_path AS section_path, "
        "c.statement AS statement, c.previous_statement AS previous_statement, "
        "c.summary AS summary ORDER BY c.kind, c.statement",
        database_=database,
    )
    return [dict(r) for r in records]


NOTIFY = "The Director shall notify the Comptroller."
REPORT = "The Director shall report to the Secretary."


# --- the diff -----------------------------------------------------------------


@pytest.mark.integration
def test_an_obligation_only_in_the_new_edition_is_added(clean_graph, database):
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("3.2", NOTIFY, Modality.SHALL), ("4.1", REPORT, Modality.SHALL)],
    )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 1, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
    changes = _changes(clean_graph, database)
    assert changes[0]["kind"] == "ADDED"
    assert changes[0]["statement"] == REPORT
    assert changes[0]["section_path"] == ["4.1"]


@pytest.mark.integration
def test_an_obligation_only_in_the_old_edition_is_removed(clean_graph, database):
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", NOTIFY, Modality.SHALL), ("4.1", REPORT, Modality.SHALL)],
    )
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", NOTIFY, Modality.SHALL)])

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 1, "MODIFIED": 0, "pairings_unapplied": 0}
    changes = _changes(clean_graph, database)
    assert changes[0]["kind"] == "REMOVED"
    assert changes[0]["statement"] == REPORT


@pytest.mark.integration
def test_an_identical_obligation_produces_no_change(clean_graph, database):
    """The case the plan's id-matching could never reach: the same words in the
    same section of two editions must be silent."""
    entries = [("3.2", NOTIFY, Modality.SHALL)]
    _seed(clean_graph, database, version_id="v1", entries=entries)
    _seed(clean_graph, database, version_id="v2", entries=entries)

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
    assert _changes(clean_graph, database) == []


@pytest.mark.integration
def test_a_reworded_obligation_in_the_same_section_is_one_modified(
    clean_graph, database
):
    """The case that matters. Matching on identity alone reports this as a removal
    plus an addition, which tells a reviewer a duty vanished and an unrelated one
    appeared — when in fact one sentence was edited."""
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1, "pairings_unapplied": 0}


@pytest.mark.integration
def test_a_modified_change_carries_both_statements(clean_graph, database):
    """A reviewer has to be able to see what actually changed."""
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])

    _diff(clean_graph, database)

    change = _changes(clean_graph, database)[0]
    assert change["previous_statement"] == NOTIFY
    assert change["statement"] == REPORT


@pytest.mark.integration
def test_a_modified_change_affects_the_new_obligation(clean_graph, database):
    """The new one is what a reviewer must now act on."""
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])

    _diff(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (:Change {kind: 'MODIFIED'})-[:AFFECTS]->(o:Obligation)"
        "<-[:MANDATES]-(v:DocumentVersion) "
        "RETURN o.statement AS statement, v.version_id AS version",
        database_=database,
    )
    assert records[0]["statement"] == REPORT
    assert records[0]["version"] == "v2"


@pytest.mark.integration
def test_a_removed_change_affects_the_obligation_that_vanished(clean_graph, database):
    """There is no new obligation to point at, and the old one is what an org
    policy's IMPLEMENTS edge still points to."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", NOTIFY, Modality.SHALL), ("4.1", REPORT, Modality.SHALL)],
    )
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", NOTIFY, Modality.SHALL)])

    _diff(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (:Change {kind: 'REMOVED'})-[:AFFECTS]->(o:Obligation)"
        "<-[:MANDATES]-(v:DocumentVersion) RETURN v.version_id AS version",
        database_=database,
    )
    assert records[0]["version"] == "v1"


@pytest.mark.integration
def test_a_section_with_two_reworded_obligations_falls_back_and_says_so(
    clean_graph, database
):
    """Pairing two against two would be a guess, and a wrong guess puts a
    reviewer's attention on the wrong sentence. Fall back and explain."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", NOTIFY, Modality.SHALL), ("3.2", REPORT, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[
            ("3.2", "The Director shall notify the Auditor.", Modality.SHALL),
            ("3.2", "The Director shall report to the Chief.", Modality.SHALL),
        ],
    )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 2, "REMOVED": 2, "MODIFIED": 0, "pairings_unapplied": 0}
    summaries = {c["summary"] for c in _changes(clean_graph, database)}
    assert any("more than one obligation" in s for s in summaries), summaries


@pytest.mark.integration
def test_a_change_is_joined_to_both_editions(clean_graph, database):
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])

    _diff(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Change)-[:FROM_VERSION]->(f:DocumentVersion) "
        "MATCH (c)-[:TO_VERSION]->(t:DocumentVersion) "
        "RETURN f.version_id AS from_version, t.version_id AS to_version",
        database_=database,
    )
    assert (records[0]["from_version"], records[0]["to_version"]) == ("v1", "v2")


@pytest.mark.integration
def test_re_running_the_diff_produces_no_duplicates(clean_graph, database):
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])

    first = _diff(clean_graph, database)
    second = _diff(clean_graph, database)

    assert first == second
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Change) RETURN count(c) AS total", database_=database
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_a_rerun_after_a_change_disappears_removes_the_stale_change(
    clean_graph, database
):
    """A re-extraction can make a change stop existing. Leaving the old :Change
    behind would show a reviewer a change that is no longer real."""
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])
    _diff(clean_graph, database)

    # The edition is re-extracted and now says what the old one said.
    clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v2'})-[:MANDATES]->(o:Obligation) "
        "DETACH DELETE o",
        database_=database,
    )
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", NOTIFY, Modality.SHALL)])

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0, "pairings_unapplied": 0}
    assert _changes(clean_graph, database) == []


@pytest.mark.integration
def test_dropping_changes_leaves_the_obligations_standing(clean_graph, database):
    """`:Change` is derived. Dropping it must not take the layer below with it."""
    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])
    _diff(clean_graph, database)

    with clean_graph.session(database=database) as session:
        dropped = session.execute_write(drop_changes, version_id="v2")

    assert dropped == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (c:Change) WITH count(c) AS changes "
        "MATCH (o:Obligation) RETURN changes, count(o) AS obligations",
        database_=database,
    )
    assert records[0]["changes"] == 0
    assert records[0]["obligations"] == 2


# --- ADR-031: pairing by wording, after section fails -------------------------


def _entry(oid: str, section: list[str], statement: str, modality: str = "SHALL"):
    return {
        "id": oid,
        "section_path": section,
        "statement": statement,
        "modality": modality,
    }


def _keyed(*entries):
    return {content_key(e["section_path"], e["statement"]): e for e in entries}


RENUMBERED_OLD = (
    "All of the DoD Components shall acquire systems, subsystems, equipment, "
    "supplies, and services in accordance with the statutory requirements for "
    "competition."
)
RENUMBERED_NEW = (
    "The DoD Components will acquire systems, subsystems, equipment, supplies, "
    "product support, sustainment, and services in accordance with the statutory "
    "requirements for competition."
)


def test_a_clause_that_moved_section_is_a_modification_not_a_replacement():
    """ADR-031, and the failure that produced it: diffing the 2018 and 2020
    editions of DoDD 5000.01 gave 0 MODIFIED, 11 ADDED, 80 REMOVED, because DoD
    renumbered enclosures into sections between them and section-based pairing
    never fired. It read as "the whole document was replaced", which was both the
    least actionable answer available and untrue."""
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], RENUMBERED_OLD))
    new = _keyed(_entry("n1", ["SECTION 1"], RENUMBERED_NEW))

    changes = _plan_changes(old, new).changes

    assert [c["kind"] for c in changes] == [MODIFIED]
    assert changes[0]["previous_statement"] == RENUMBERED_OLD
    assert changes[0]["obligation_id"] == "n1"


def test_a_pairing_found_by_wording_carries_its_evidence():
    """ADR-031 requires it: a row a reader cannot interrogate is what ADR-015
    refused to produce, and this one was not found by structure."""
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], RENUMBERED_OLD))
    new = _keyed(_entry("n1", ["SECTION 1"], RENUMBERED_NEW))

    summary = _plan_changes(old, new).changes[0]["summary"]

    assert "acquire" in summary or "wording" in summary.lower()
    assert "ENCLOSURE 1" in summary and "SECTION 1" in summary


def test_a_wording_pairing_asks_the_pairing_question_not_the_implements_one():
    """Which scorer the diff calls is visible to a person, and only here.

    Both scorers build their rationale from the same `_facts()` head, so every
    other assertion in this file reads the same either way — swap the import for
    `score_pair as score_pairing` and nothing else complains, while the summary
    a reviewer reads reverts to telling them to confirm the org clause
    discharges the higher duty. That is advice about a relationship nobody is
    claiming here: this pass asks whether one clause is the other reworded.
    Computed from the scorers rather than pinned as a literal, so it follows the
    sentences test_links.py owns instead of duplicating them.
    """
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], RENUMBERED_OLD))
    new = _keyed(_entry("n1", ["SECTION 1"], RENUMBERED_NEW))

    summary = _plan_changes(old, new).changes[0]["summary"]

    assert score_pairing(RENUMBERED_NEW, RENUMBERED_OLD).rationale in summary
    assert "whether the newer clause is the older one reworded" in summary
    assert score_pair(RENUMBERED_NEW, RENUMBERED_OLD).rationale not in summary
    assert "discharges the higher duty" not in summary


def test_two_unrelated_clauses_are_not_paired():
    """The risk ADR-031 names: a false pairing reports a MODIFIED that never
    happened, and a reviewer who trusts it reviews a change that does not exist.
    Over-reporting is visible; a wrong pairing is not."""
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], "The Director shall notify the Comptroller of any breach."))
    new = _keyed(_entry("n1", ["SECTION 9"], "Records shall be destroyed at the end of their retention period."))

    changes = _plan_changes(old, new).changes

    assert sorted(c["kind"] for c in changes) == [ADDED, REMOVED]


def test_section_pairing_still_wins_where_it_applies():
    """Structure first: a section holding one unmatched clause each side has been
    edited, and no measurement improves on that."""
    old = _keyed(_entry("o1", ["SECTION 2"], "Components shall report annually."))
    new = _keyed(_entry("n1", ["SECTION 2"], "Components shall report every year."))

    changes = _plan_changes(old, new).changes

    assert [c["kind"] for c in changes] == [MODIFIED]
    assert "reworded" in changes[0]["summary"]


def test_a_near_tie_falls_back_rather_than_picking_the_higher_score():
    """ADR-031 keeps ADR-015's answer to "we do not know", and this is the case
    that needs the margin rather than mere tie-breaking.

    These two candidates score 0.833 and 0.800 against the same clause — close
    enough that this measure cannot tell them apart, far enough that a rule
    comparing scores alone would confidently choose the first. A wrong pairing
    reports a MODIFIED that never happened, and unlike over-reporting it is
    invisible to the reviewer who acts on it.
    """
    before = (
        "Components shall submit the annual report to the Comptroller by 31 March "
        "each year."
    )
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], before))
    new = _keyed(
        _entry("n1", ["SECTION 1"], before.replace("31 March", "31 April")),
        _entry(
            "n2",
            ["SECTION 2"],
            "Components shall submit the annual report to the Comptroller by 30 April.",
        ),
    )

    changes = _plan_changes(old, new).changes

    assert MODIFIED not in [c["kind"] for c in changes], (
        "a near-tie was resolved by score alone; the margin is what stops that"
    )


def test_an_exact_tie_falls_back_too():
    """The simpler half, which needs no margin — but a rule that only handled
    exact ties would leave the near-tie above unguarded."""
    shared = "Components shall submit the annual report to the Comptroller by 31 March."
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], shared))
    new = _keyed(
        _entry("n1", ["SECTION 1"], shared.replace("31 March", "31 April")),
        _entry("n2", ["SECTION 2"], shared.replace("31 March", "30 April")),
    )

    changes = _plan_changes(old, new).changes

    assert MODIFIED not in [c["kind"] for c in changes]


# --- §2: every wording-pass outcome is recorded --------------------------------


def _score_table(monkeypatch, table: dict[tuple[str, str], float]) -> None:
    """Replace the diff's scorer with a lookup table.

    `table` maps (before_statement, after_statement) to a confidence — the
    old→new reading order the fixtures are written in. Anything absent scores
    None, exactly as `score_pairing` does for a pair sharing no content words.
    The table may hold values below MIN_CONFIDENCE on purpose: the real scorer
    never returns those, and the vacuity test needs a scorer that does.
    """

    def fake_score_pairing(after_statement: str, before_statement: str):
        confidence = table.get((before_statement, after_statement))
        if confidence is None:
            return None
        return Candidate(confidence=confidence, rationale="stub rationale")

    monkeypatch.setattr(
        "policy_grapher.changes.diff.score_pairing", fake_score_pairing
    )


def _outcomes(plan) -> dict[tuple[str, str], str]:
    return {(c["old_id"], c["new_id"]): c["outcome"] for c in plan.candidates}


def _records(plan) -> dict[tuple[str, str], dict]:
    """Whole candidate records by pair, for the assertions `_outcomes` cannot
    make: it projects the label away from the confidence and the rationale, and
    those two are what Task 4 persists and a reviewer reads."""
    return {(c["old_id"], c["new_id"]): c for c in plan.candidates}


def test_the_greedy_loop_labels_all_three_outcomes_in_one_run(monkeypatch):
    """The chain the spec's containment argument is built on: the 0.80 pair
    loses its partner to the 0.90 pair (partner_taken), and the 0.76 tail is
    within the margin of the 0.80 rival (contested). The outcome is the first
    rule that fired, in code order — not four disjoint predicates."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old beta", "new alpha"): 0.80,
            ("old beta", "new beta"): 0.76,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    plan = _plan_changes(old, new)

    assert len(plan.candidates) == 3
    assert _outcomes(plan) == {
        ("o1", "n1"): "auto_paired",
        ("o2", "n1"): "partner_taken",
        ("o2", "n2"): "contested",
    }
    assert [c["obligation_id"] for c in plan.changes if c["kind"] == MODIFIED] == [
        "n1"
    ]
    assert plan.pairings_unapplied == 0


def test_a_contested_label_needs_no_taken_partner(monkeypatch):
    """The partner-free fork: 0.80 and 0.78 share one clause, the margin
    declines both, and nothing was accepted — so `contested` cannot be an
    artifact of a taken partner. The paired sets must come out untouched."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.80,
            ("old alpha", "new beta"): 0.78,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"), _entry("n2", ["C"], "new beta"))

    plan = _plan_changes(old, new)

    assert _outcomes(plan) == {
        ("o1", "n1"): "contested",
        ("o1", "n2"): "contested",
    }
    assert MODIFIED not in [c["kind"] for c in plan.changes]


def test_a_pair_whose_both_sides_were_taken_is_partner_taken(monkeypatch):
    """Both endpoints can be consumed — the decline fires when *either* is —
    so up to two auto_paired winners exist for one declined pair. The queue
    names each side's taker (Task 10); this pins the state it reads from."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.95,
            ("old beta", "new beta"): 0.91,
            ("old alpha", "new beta"): 0.85,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    assert outcomes[("o2", "n2")] == "auto_paired"
    assert outcomes[("o1", "n2")] == "partner_taken"


def test_recording_a_sub_threshold_rival_does_not_change_the_pairing(monkeypatch):
    """The invariant the whole feature hangs on: a 0.74 rival is recorded, and
    the 0.78 pair still auto-pairs. `_best_elsewhere` has no confidence filter
    of its own, so widening `scored` down to MIN_CONFIDENCE would flip this
    pair to contested — that mutant is what this test exists to kill."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.78,
            ("old alpha", "new beta"): 0.74,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"), _entry("n2", ["C"], "new beta"))

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    assert outcomes[("o1", "n2")] == "below_threshold"
    assert MODIFIED in [c["kind"] for c in plan.changes]


def test_a_sub_threshold_candidate_survives_only_through_an_unpaired_endpoint(
    monkeypatch,
):
    """The bound, and its timing. o1–n2's 0.60 has both endpoints consumed by
    the loop, so it is dropped; o1–n3's 0.60 is kept only because n3 finished
    unpaired and it is n3's best; o2–n3's 0.50 is not within PAIRING_MARGIN of
    that best. Judged before the loop, every endpoint is still unpaired and
    all three would survive — which is the mutant."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old beta", "new beta"): 0.85,
            ("old alpha", "new beta"): 0.60,
            ("old alpha", "new gamma"): 0.60,
            ("old beta", "new gamma"): 0.50,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(
        _entry("n1", ["C"], "new alpha"),
        _entry("n2", ["D"], "new beta"),
        _entry("n3", ["E"], "new gamma"),
    )

    plan = _plan_changes(old, new)

    outcomes = _outcomes(plan)
    assert outcomes[("o1", "n1")] == "auto_paired"
    below = {pair for pair, outcome in outcomes.items() if outcome == "below_threshold"}
    assert below == {("o1", "n3")}


def test_a_pair_below_the_floor_is_not_recorded_even_when_the_scorer_returns_it(
    monkeypatch,
):
    """score_pairing already returns None under MIN_CONFIDENCE, so a fixture
    that leans on it proves nothing — the spec's vacuity warning. The stub is
    the deliberately lowered floor: it returns 0.20, and the diff's own guard
    must refuse to record it."""
    _score_table(monkeypatch, {("old alpha", "new alpha"): 0.20})
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"))

    plan = _plan_changes(old, new)

    assert plan.candidates == []


def test_a_recorded_candidate_carries_the_score_it_was_judged_on(monkeypatch):
    """A label alone is not a reviewable record. Task 4 persists `confidence`
    and `rationale` verbatim and Task 10 puts them on a person's screen, so a
    zeroed confidence or a blank rationale is a wrong number in front of the
    reviewer, not a cosmetic defect — and `_outcomes` projects both away.

    Whole-record equality, so the key set is pinned too: Task 4's writer reads
    exactly these five keys. The three exits carry three different confidences
    on purpose, so a record cannot quietly borrow another row's."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old beta", "new alpha"): 0.80,
            ("old beta", "new beta"): 0.76,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    records = _records(_plan_changes(old, new))

    assert records[("o1", "n1")] == {
        "old_id": "o1",
        "new_id": "n1",
        "confidence": 0.90,
        "rationale": "stub rationale",
        "outcome": "auto_paired",
    }
    assert records[("o2", "n1")] == {
        "old_id": "o2",
        "new_id": "n1",
        "confidence": 0.80,
        "rationale": "stub rationale",
        "outcome": "partner_taken",
    }
    assert records[("o2", "n2")] == {
        "old_id": "o2",
        "new_id": "n2",
        "confidence": 0.76,
        "rationale": "stub rationale",
        "outcome": "contested",
    }


def test_a_sub_threshold_runner_up_within_the_margin_is_kept(monkeypatch):
    """The other half of the bound: an endpoint's best is kept, and so is
    anything within PAIRING_MARGIN of it.

    o1–n2 at 0.58 is nobody's best — o1's best is 0.60 and n2's is 0.70 — and it
    survives only because it is within the margin of o1's best. That is the pair
    the tolerance exists for: two sub-threshold candidates this close are the
    case the measure cannot separate, so a person arbitrates, which they cannot
    do if only the winner was kept. Narrowing the rule to strict bests
    (`<= 0.0`) drops exactly this record while every other test stays green."""
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.60,
            ("old alpha", "new beta"): 0.58,
            ("old beta", "new beta"): 0.70,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"), _entry("o2", ["B"], "old beta"))
    new = _keyed(_entry("n1", ["C"], "new alpha"), _entry("n2", ["D"], "new beta"))

    plan = _plan_changes(old, new)

    records = _records(plan)
    assert set(records) == {("o1", "n1"), ("o1", "n2"), ("o2", "n2")}
    assert records[("o1", "n2")] == {
        "old_id": "o1",
        "new_id": "n2",
        "confidence": 0.58,
        "rationale": "stub rationale",
        "outcome": "below_threshold",
    }
    assert MODIFIED not in [c["kind"] for c in plan.changes]


# --- §2: the diff writes and drops its candidate record ------------------------


def _candidate_edges(driver, database, *, a: str, b: str) -> int:
    """Candidate edges between two editions' obligations, either orientation.

    Undirected on purpose: a reversed Triage run writes its edges the other
    way, and a directed count would hide exactly the orphans the drop must
    reach.
    """
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $a})-[:MANDATES]->(:Obligation)"
        "-[r:PAIRING_CANDIDATE]-"
        "(:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: $b}) "
        "RETURN count(r) AS total",
        {"a": a, "b": b},
        database_=database,
    )
    return records[0]["total"]


@pytest.mark.integration
def test_rediffing_the_same_pair_leaves_no_stale_candidate(clean_graph, database):
    """Both endpoints survive here — only the plan changed — so nothing deletes
    the edge as a side effect (the rebuild path's drop_obligations cannot save
    us, and drop_changes structurally cannot: a PAIRING_CANDIDATE hangs off no
    :Change node). Only the pair's own drop can remove it."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.WILL)],
    )
    _diff(clean_graph, database)
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1

    # A re-extraction of v2 now also finds the old clause verbatim, so pass 1
    # matches it and the wording pass has nothing left to pair. The auto_paired
    # edge the first run wrote answers a question the diff no longer asks.
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    counts = _diff(clean_graph, database)

    assert counts["MODIFIED"] == 0
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 0


@pytest.mark.integration
def test_rediffing_one_pair_leaves_the_adjacent_pairs_candidates_intact(
    clean_graph, database
):
    """A middle edition's obligations belong to two pairs. A drop scoped to
    "any candidate edge touching either edition" would delete the neighbouring
    diff's record with this pair's — which is why DROP_CANDIDATES anchors both
    ends through :MANDATES."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.WILL)],
    )
    # v3 carries v2's clause verbatim but renumbered again, so the v2→v3 diff
    # pairs it by wording at confidence 1.0.
    _seed(
        clean_graph,
        database,
        version_id="v3",
        entries=[("5.1", RENUMBERED_NEW, Modality.WILL)],
    )
    _diff(clean_graph, database, old="v1", new="v2")
    _diff(clean_graph, database, old="v2", new="v3")
    assert _candidate_edges(clean_graph, database, a="v2", b="v3") == 1

    _diff(clean_graph, database, old="v1", new="v2")

    assert _candidate_edges(clean_graph, database, a="v2", b="v3") == 1
    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1


@pytest.mark.integration
def test_a_reversed_runs_edges_are_cleaned_by_the_next_chronological_run(
    clean_graph, database
):
    """Triage accepts arbitrary direction, so a reversed GET writes its edges
    the other way round. The undirected drop lets the chronological run reach
    them; a directional match would leave them orphaned forever while deleting
    only the well-oriented ones."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.WILL)],
    )
    _diff(clean_graph, database, old="v2", new="v1")
    _diff(clean_graph, database, old="v1", new="v2")

    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v1'})-[:MANDATES]->(:Obligation)"
        "-[r:PAIRING_CANDIDATE]->"
        "(:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: 'v2'}) "
        "RETURN count(r) AS total",
        database_=database,
    )
    assert records[0]["total"] == 1


@pytest.mark.integration
def test_drop_candidates_counts_relationships_not_nodes(clean_graph, database):
    """A candidate is an edge between two obligations that stay standing.
    nodes_deleted here would always be 0 — compare drop_changes, whose unit is
    the :Change node — and a caller reading it would believe the drop did
    nothing."""
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.WILL)],
    )
    _diff(clean_graph, database)

    with clean_graph.session(database=database) as session:
        dropped = session.execute_write(
            drop_candidates, from_version_id="v1", to_version_id="v2"
        )

    assert dropped == 1
    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation) RETURN count(o) AS obligations", database_=database
    )
    assert records[0]["obligations"] == 2


@pytest.mark.integration
def test_a_persisted_candidate_carries_its_confidence_rationale_and_outcome(
    clean_graph, database
):
    """Counting edges cannot see this. Blank the SET clause in WRITE_CANDIDATES
    and every other test in this file still passes, while every candidate edge
    in the graph carries a null outcome and no rationale — and Task 10 puts
    those three in front of a person deciding whether one clause is the other
    reworded. A question asked with its evidence missing is worse than one not
    asked.

    Whole-record equality rather than three presence checks: a wrong-but-present
    value is the failure that matters here, and `is not None` passes on it. The
    rationale is computed from the scorer rather than pinned as a literal, so it
    follows the sentences test_links.py owns instead of duplicating them; the
    confidence is literal because these two statements share all of the shorter
    one's distinctive wording, and 1.0 is a value a reader can check by eye.
    """
    _seed(
        clean_graph,
        database,
        version_id="v1",
        entries=[("3.2", RENUMBERED_OLD, Modality.SHALL)],
    )
    _seed(
        clean_graph,
        database,
        version_id="v2",
        entries=[("4.1", RENUMBERED_NEW, Modality.WILL)],
    )
    _diff(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v1'})-[:MANDATES]->(:Obligation)"
        "-[r:PAIRING_CANDIDATE]->"
        "(:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: 'v2'}) "
        "RETURN r.confidence AS confidence, r.rationale AS rationale, "
        "r.outcome AS outcome",
        database_=database,
    )

    assert [dict(r) for r in records] == [
        {
            "confidence": 1.0,
            "rationale": score_pairing(RENUMBERED_NEW, RENUMBERED_OLD).rationale,
            "outcome": "auto_paired",
        }
    ]
