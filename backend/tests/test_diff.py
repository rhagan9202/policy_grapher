"""Diffing two editions of one instrument into changes a reviewer can read."""

import pytest

from policy_grapher.changes.diff import (
    ADDED,
    AUTO_PAIRED,
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
    """Which scorer the diff calls is visible to a person, on the candidate.

    Both scorers build their rationale from the same `_facts()` head, so every
    other assertion in this file reads the same either way — swap the import for
    `score_pair as score_pairing` and nothing else complains, while the sentence
    a reviewer reads reverts to telling them to confirm the org clause
    discharges the higher duty. That is advice about a relationship nobody is
    claiming here: this pass asks whether one clause is the other reworded.
    Computed from the scorers rather than pinned as a literal, so it follows the
    sentences test_links.py owns instead of duplicating them.

    The assertion used to be made against the `:Change` summary, which was the
    only place the sentence appeared. It now lives on the candidate instead —
    see the test below for why it had to leave the summary — and the candidate
    is where the pairing reviewer reads it, on the Pairings screen. The
    guarantee is unchanged; only its home is.
    """
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], RENUMBERED_OLD))
    new = _keyed(_entry("n1", ["SECTION 1"], RENUMBERED_NEW))

    candidate = _plan_changes(old, new).candidates[0]

    assert candidate["outcome"] == AUTO_PAIRED
    assert score_pairing(RENUMBERED_NEW, RENUMBERED_OLD).rationale in candidate["rationale"]
    assert "whether the newer clause is the older one reworded" in candidate["rationale"]
    assert score_pair(RENUMBERED_NEW, RENUMBERED_OLD).rationale not in candidate["rationale"]
    assert "discharges the higher duty" not in candidate["rationale"]


def test_a_change_summary_does_not_ask_the_pairing_reviewers_question():
    """A `:Change` is read on Triage, by someone asking a different question.

    The pairing reviewer is deciding whether the newer clause is the older one
    reworded. By the time a change reaches Triage that has been decided — the
    row exists *because* it was — and the reader is a compliance analyst asking
    what changed and what of theirs it touches. Ending the one line of prose per
    row with another reviewer's open question put a question to them that is not
    theirs and that they cannot act on.

    The facts stay: they say what the pairing was based on, which is the part
    that survives the change of audience.
    """
    old = _keyed(_entry("o1", ["ENCLOSURE 1"], RENUMBERED_OLD))
    new = _keyed(_entry("n1", ["SECTION 1"], RENUMBERED_NEW))

    summary = _plan_changes(old, new).changes[0]["summary"]

    assert "whether the newer clause is the older one reworded" not in summary
    # Still says what changed, and on what evidence.
    assert "ENCLOSURE 1" in summary and "SECTION 1" in summary
    assert "distinctive wording" in summary


def test_a_declined_pairing_says_what_changed_before_why_it_reads_that_way():
    """The caveat replaced the description instead of following it.

    A section holding more than one changed obligation is reported as a removal
    and an addition rather than a guessed pairing, and that is worth saying. But
    it was said *instead of* "the obligation in section X is gone", so the one
    line an analyst gets explained the diff's own bookkeeping and never the
    change. Both facts fit; the reader's comes first.
    """
    old = _keyed(
        _entry("o1", ["3.2"], "The Director shall notify the Comptroller."),
        _entry("o2", ["3.2"], "The Director shall record the notification."),
    )
    new = _keyed(
        _entry("n1", ["3.2"], "Records shall be destroyed after ten years."),
        _entry("n2", ["3.2"], "Access shall be reviewed twice a year."),
    )

    changes = _plan_changes(old, new).changes
    removed = [c for c in changes if c["kind"] == REMOVED]
    assert removed, [c["kind"] for c in changes]

    summary = removed[0]["summary"]
    assert "is gone" in summary, summary
    assert "more than one obligation that changed" in summary, summary


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
        return Candidate(
            confidence=confidence,
            rationale="stub rationale",
            facts="stub facts",
        )

    monkeypatch.setattr(
        "policy_grapher.changes.diff.score_pairing", fake_score_pairing
    )


def _outcomes(plan) -> dict[tuple[str, str], str]:
    return {(c["old_id"], c["new_id"]): c["outcome"] for c in plan.candidates}


def _records(plan) -> dict[tuple[str, str], dict]:
    """Whole candidate records by pair, for the assertions `_outcomes` cannot
    make: it projects the label away from the confidence and the rationale, and
    those two are what `WRITE_CANDIDATES` persists and a reviewer reads."""
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
    so up to two auto_paired winners exist for one declined pair. The pairing
    queue names each side's taker; this pins the state it reads from."""
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


def test_a_pair_whose_old_side_alone_was_taken_is_partner_taken(monkeypatch):
    """The arm neither fixture above can kill.

    The chain fixture's declined pair loses its *new* side, and the both-sides
    fixture loses both — so deleting `before["id"] in paired_old` from the guard
    left every test in this file green while the label flipped to `contested`.
    Structure is unaffected either way (the margin rule re-declines the pair), but
    the labels are the remedy the screen prints: `contested` tells a reviewer the
    two candidates were too close to separate, where the truth is that a
    higher-scoring pair took one clause and a named winner exists to mark
    distinct first.

    Here the 0.80 pair shares only its *old* clause with the 0.90 winner, and its
    new clause is taken by nothing.
    """
    _score_table(
        monkeypatch,
        {
            ("old alpha", "new alpha"): 0.90,
            ("old alpha", "new beta"): 0.80,
        },
    )
    old = _keyed(_entry("o1", ["A"], "old alpha"))
    new = _keyed(_entry("n1", ["B"], "new alpha"), _entry("n2", ["C"], "new beta"))

    plan = _plan_changes(old, new)

    assert _outcomes(plan) == {
        ("o1", "n1"): "auto_paired",
        ("o1", "n2"): "partner_taken",
    }
    assert [c["obligation_id"] for c in plan.changes if c["kind"] == MODIFIED] == [
        "n1"
    ]


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
    """A label alone is not a reviewable record. `WRITE_CANDIDATES` persists
    `confidence` and `rationale` verbatim and the pairing screen puts them in
    front of a reviewer, so a
    zeroed confidence or a blank rationale is a wrong number in front of the
    reviewer, not a cosmetic defect — and `_outcomes` projects both away.

    Whole-record equality, so the key set is pinned too: `WRITE_CANDIDATES`
    reads exactly these five keys. The three exits carry three different confidences
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
    ends through :MANDATES.

    Re-diffed in *both* directions on purpose. Re-diffing only the earlier pair
    puts the shared edition on the `to` side every time, so a drop that kept its
    from-side anchor and lost the other would pass while still deleting the
    neighbour's edge as collateral. The later-pair re-diff puts v2 on the `from`
    side and makes the second anchor load-bearing too.
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

    # The mirror, with the shared edition on the `from` side this time.
    _diff(clean_graph, database, old="v2", new="v3")

    assert _candidate_edges(clean_graph, database, a="v1", b="v2") == 1
    assert _candidate_edges(clean_graph, database, a="v2", b="v3") == 1


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
    in the graph carries a null outcome and no rationale — and the pairing
    screen puts those three in front of a person deciding whether one clause is
    the other reworded. A question asked with its evidence missing is worse than one not
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


@pytest.mark.integration
def test_the_declined_candidates_are_persisted_too_not_just_the_paired_one(
    clean_graph, database
):
    """The pairs a human is meant to settle are the declined ones, so those are
    the records that must survive the write — and every other fixture in this
    block yields exactly one candidate, always `auto_paired`. That leaves three
    mutants alive: a write filtered to `outcome == "auto_paired"`, a truncated
    `plan.candidates[:1]`, and `SET r.outcome = 'auto_paired'` as a literal. The
    first two would silently drop every question the queue exists to ask; the
    third would tell a reviewer the system had made a pairing it actually
    declined.

    The fixture is the fallback case `test_a_section_with_two_reworded_
    obligations_falls_back_and_says_so` already relies on: one section holding
    two reworded clauses each side, which pairs nothing and declines both at
    0.67. Equality on the whole ordered list, not on a subset, is what kills all
    three — a filtered or truncated write changes the list's length, and a
    literal outcome changes its contents.
    """
    notify_auditor = "The Director shall notify the Auditor."
    report_chief = "The Director shall report to the Chief."
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
            ("3.2", notify_auditor, Modality.SHALL),
            ("3.2", report_chief, Modality.SHALL),
        ],
    )

    _diff(clean_graph, database)

    records, _, _ = clean_graph.execute_query(
        "MATCH (:DocumentVersion {version_id: 'v1'})-[:MANDATES]->(old:Obligation)"
        "-[r:PAIRING_CANDIDATE]->"
        "(new:Obligation)<-[:MANDATES]-(:DocumentVersion {version_id: 'v2'}) "
        "RETURN old.statement AS old_statement, new.statement AS new_statement, "
        "r.confidence AS confidence, r.rationale AS rationale, r.outcome AS outcome "
        "ORDER BY old.statement, new.statement",
        database_=database,
    )

    # Two of the three distinctive words survive each rewording, so both pairs
    # land under PAIRING_CONFIDENCE and neither is paired.
    two_of_three = 0.6666666666666666
    assert [dict(r) for r in records] == [
        {
            "old_statement": NOTIFY,
            "new_statement": notify_auditor,
            "confidence": two_of_three,
            "rationale": score_pairing(notify_auditor, NOTIFY).rationale,
            "outcome": "below_threshold",
        },
        {
            "old_statement": REPORT,
            "new_statement": report_chief,
            "confidence": two_of_three,
            "rationale": score_pairing(report_chief, REPORT).rationale,
            "outcome": "below_threshold",
        },
    ]


# --- decisions threaded into the plan (spec §3) --------------------------------
#
# No second scorer stub here: every test below drives the `_score_table` helper
# defined earlier in this file. `changes.diff` imports `score_pairing` into its
# own namespace, so `changes.diff.score_pairing` is the only
# seam that rebinds anything — patching `links.propose` would leave the real
# scorer running behind an inert stub. `_score_table`'s keys are
# (before_statement, after_statement), old→new, which is the order every table
# in this section is written in.


def test_a_paired_decision_beats_the_section_rule(monkeypatch):
    """The fixture rev. 4 could not pass. The decision's old clause sits alone
    in a section with a *different* new clause — exactly what pass 2 pairs
    unconditionally — and the human's pairing must still win. Pass 2 reads only
    the by_section grouping, so the verdict has to be applied before that
    grouping is built; anything later lets a structural heuristic consume a
    human verdict's obligation and shelve the verdict."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(
        # WILL, not SHALL: the two sides must differ, or an implementation
        # taking `modality` off `before` reads identically to one taking it off
        # `after`. The 2020 DoD re-issue replaced the directive `shall` with
        # `will` (ADR-025), so a reworded clause changing modality is the
        # ordinary case, not a contrived one.
        _entry("n1", ["7.1"], "The Director will inform the Comptroller in writing.", "WILL"),
        _entry("n2", ["3.2"], "Records shall be destroyed on schedule."),
    )

    result = _plan_changes(old, new, {("o1", "n1"): "paired"})

    modified = [c for c in result.changes if c["kind"] == MODIFIED]
    assert [(c["obligation_id"], c["previous_statement"]) for c in modified] == [
        ("n1", "The Director shall notify the Comptroller.")
    ]
    assert modified[0]["summary"] == (
        "A reviewer paired these clauses: they are one obligation, "
        "reworded between these two editions."
    )
    # The row must describe the clause a reviewer now has to act on, which is
    # the one from the `to` edition — both fields taken from `after`, not
    # `before`. `section_path` is where Triage sends them and `modality` is
    # what ranks the row, so sourcing either from the wrong side points them at
    # a section the new edition may not even have.
    assert (modified[0]["section_path"], modified[0]["modality"]) == (["7.1"], "WILL")
    assert modified[0]["statement"] == (
        "The Director will inform the Comptroller in writing."
    )
    assert sorted(c["kind"] for c in result.changes) == [ADDED, MODIFIED]
    added = [c for c in result.changes if c["kind"] == ADDED]
    assert added[0]["obligation_id"] == "n2"
    # `pairings_unapplied` counts pass 1's pre-emptions and nothing else. This
    # verdict is one pass 2 would have consumed had it been applied any later,
    # so a count that widened to include pass-2 consumption would report this
    # reviewer's decision as dropped when it was in fact honoured — a number
    # that lies in the direction of blaming the system for the reviewer's work
    # being ignored. The assertions above pin the changes; only this one pins
    # the number.
    assert result.pairings_unapplied == 0


def test_a_paired_decision_pairs_what_nothing_scored_across_sections(monkeypatch):
    """A complete rewording sharing no content words is never scored at all —
    the silent exclusion the problem section names as the case a human most
    obviously beats the measure. The verdict must pair it anyway, across
    differing section paths, at no confidence whatsoever."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["SECTION 4"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("o1", "n1"): "paired"})

    assert [c["kind"] for c in result.changes] == [MODIFIED]
    assert result.changes[0]["obligation_id"] == "n1"
    assert result.changes[0]["previous_statement"] == "The Director shall notify the Comptroller."
    assert result.pairings_unapplied == 0


def test_a_decision_keyed_in_the_other_orientation_still_applies(monkeypatch):
    """The record's canonical direction is older→newer, but this layer binds
    whatever from/to the caller passed — a reversed Triage run flips which side
    each id falls on — so a verdict must apply however the ids fall out."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["SECTION 4"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("n1", "o1"): "paired"})

    assert [c["kind"] for c in result.changes] == [MODIFIED]
    assert result.changes[0]["obligation_id"] == "n1"
    assert result.pairings_unapplied == 0


def test_a_paired_decision_pass_1_preempted_is_counted_not_dropped(monkeypatch):
    """Pass 1 is the one thing that may pre-empt a verdict: an identical clause
    persisting in both editions is a fact, not a pairing judgement. The verdict
    is counted, never dropped or rewritten."""
    _score_table(monkeypatch, {})
    persisting = "The Director shall notify the Comptroller."
    old = _keyed(_entry("o1", ["3.2"], persisting))
    new = _keyed(
        _entry("n1", ["3.2"], persisting),
        _entry("n2", ["SECTION 4"], "Records shall be destroyed on schedule."),
    )

    decisions = {("o1", "n2"): "paired"}
    result = _plan_changes(old, new, decisions)

    assert result.pairings_unapplied == 1
    assert [c["kind"] for c in result.changes] == [ADDED]
    assert result.changes[0]["obligation_id"] == "n2"
    assert decisions == {("o1", "n2"): "paired"}


def test_a_distinct_decision_suppresses_the_section_rule(monkeypatch):
    """Alone in a section, the two clauses are exactly what pass 2 re-pairs on
    structure — the verdict must stop it, or `distinct` is only honoured where
    the wording pass happens to be the decliner."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["3.2"], "The Director shall notify the Auditor."))

    control = _plan_changes(old, new)
    assert [c["kind"] for c in control.changes] == [MODIFIED]

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]
    # A verdict this run *honoured* must not be reported as one it could not
    # apply. `pairings_unapplied` says a reviewer's decision did not land, so a
    # count incremented here would tell them the opposite of what happened.
    assert result.pairings_unapplied == 0


def test_a_distinct_decision_suppresses_a_wording_pairing(monkeypatch):
    """The other decliner. The pair scores well above PAIRING_CONFIDENCE, so
    without the verdict it auto-pairs — and a settled pair must not come back
    as a candidate either: the :PairingDecision is the record, and a candidate
    edge would re-ask a settled question."""
    old_statement = "The Director shall notify the Comptroller."
    new_statement = "The Director must notify the Comptroller promptly."
    _score_table(monkeypatch, {(old_statement, new_statement): 0.9})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], old_statement))
    new = _keyed(_entry("n1", ["SECTION 4"], new_statement))

    control = _plan_changes(old, new)
    assert [c["kind"] for c in control.changes] == [MODIFIED]
    assert [c["outcome"] for c in control.candidates] == ["auto_paired"]

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]
    assert result.candidates == []
    assert result.pairings_unapplied == 0


def test_a_distinct_sub_threshold_pair_neither_records_nor_shadows(monkeypatch):
    """The reviewer said *not this one*, so its score must not shadow the
    endpoint's next-best live candidate in the bound. o1's settled 0.60 would
    otherwise be o1's best and 0.50 falls outside PAIRING_MARGIN of it; n2
    cannot rescue the record either, because n2's own best is 0.58."""
    o1_statement = "The Director shall notify the Comptroller."
    o2_statement = "Components shall report annually to the Secretary."
    n1_statement = "The Director shall inform the Comptroller."
    n2_statement = "Reports go to the Secretary each year."
    _score_table(
        monkeypatch,
        {
            (o1_statement, n1_statement): 0.60,
            (o1_statement, n2_statement): 0.50,
            (o2_statement, n2_statement): 0.58,
        },
    )
    old = _keyed(
        _entry("o1", ["1.1"], o1_statement),
        _entry("o2", ["2.2"], o2_statement),
    )
    new = _keyed(
        _entry("n1", ["8.1"], n1_statement),
        _entry("n2", ["9.9"], n2_statement),
    )

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    assert MODIFIED not in [c["kind"] for c in result.changes]
    recorded = {(c["old_id"], c["new_id"]): c for c in result.candidates}
    assert ("o1", "n1") not in recorded
    assert recorded[("o1", "n2")]["outcome"] == "below_threshold"
    assert recorded[("o2", "n2")]["outcome"] == "below_threshold"
    assert len(recorded) == 2
    assert result.pairings_unapplied == 0


@pytest.mark.integration
def test_diff_versions_applies_a_recorded_pairing_decision(clean_graph, database):
    """No wiring by the caller: `diff_versions` reads the decisions itself,
    scoped through :MANDATES to the two named editions, so a verdict recorded
    through /pairings takes effect on the very next diff — Triage's or the
    queue's alike. The two statements share no content words, so nothing here
    is scored: only the decision can produce the MODIFIED."""
    from policy_grapher.extraction.schema import obligation_id
    from policy_grapher.links.pairing import record_pairing

    old_statement = "The Director shall notify the Comptroller of any breach."
    new_statement = "Records shall be destroyed at the end of their retention period."
    _seed(
        clean_graph, database, version_id="v1",
        entries=[("3.2", old_statement, Modality.SHALL)],
    )
    _seed(
        clean_graph, database, version_id="v2",
        entries=[("9.9", new_statement, Modality.SHALL)],
    )
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=obligation_id("v1", ["3.2"], old_statement),
            new_id=obligation_id("v2", ["9.9"], new_statement),
            verdict="paired",
            actor="tester",
            rationale="a complete rewording the measure cannot see",
        )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1, "pairings_unapplied": 0}
    change = _changes(clean_graph, database)[0]
    assert change["previous_statement"] == old_statement
    assert change["statement"] == new_statement
    assert "reviewer paired" in change["summary"]


@pytest.mark.integration
def test_diff_versions_reports_a_verdict_pass_1_preempted(clean_graph, database):
    """Where `pairings_unapplied` comes from, pinned on the counts dict itself.

    Every other assertion on this key in this file expects 0, which a
    `diff_versions` hardcoding 0 satisfies exactly as well as one reading the
    plan — the whole file passes under that mutant. It takes a run whose count
    is *not* zero to say the number is sourced, and this is the first task in
    which one exists. The pairings queue route (a later task) reads this dict
    rather than the Triage response, so the contract is pinned here, not only
    at the API boundary.

    9.9 is word-for-word identical across the two editions, so pass 1 matches
    it and the verdict naming it has nothing left to bind. 3.2 is reworded and
    alone in its section, so the section rule still does the ordinary work —
    whole-dict equality is what says the run reported the verdict *and* did the
    work, rather than falling over on the decision.
    """
    from policy_grapher.extraction.schema import obligation_id
    from policy_grapher.links.pairing import record_pairing

    persisting = "Components shall retain records for seven years."
    _seed(
        clean_graph, database, version_id="v1",
        entries=[("3.2", NOTIFY, Modality.SHALL), ("9.9", persisting, Modality.SHALL)],
    )
    _seed(
        clean_graph, database, version_id="v2",
        entries=[("3.2", REPORT, Modality.SHALL), ("9.9", persisting, Modality.SHALL)],
    )
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=obligation_id("v1", ["9.9"], persisting),
            new_id=obligation_id("v2", ["3.2"], REPORT),
            verdict="paired",
            actor="tester",
            rationale="the retention clause became the reporting one",
        )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1, "pairings_unapplied": 1}
    # Reported, never retracted: the count is this run's inability to apply the
    # verdict, not a change to what the reviewer decided.
    records, _, _ = clean_graph.execute_query(
        "MATCH (p:PairingDecision) RETURN p.verdict AS verdict", database_=database
    )
    assert [r["verdict"] for r in records] == ["paired"]


# --- §3 review round: what a decline says, and what a verdict must be ----------


def test_a_distinct_decline_does_not_blame_the_ambiguity_rule(monkeypatch):
    """A reviewer must not read their own decision back as the machine's
    excuse. AMBIGUOUS_SECTION says two things — that the section holds more
    than one changed obligation, and that the pairing was declined for want of
    a safe guess — and both are false here: the section holds one on each side,
    and a person decided. Newly reachable, because before verdicts existed pass
    2 never declined a one-each-side section."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["3.2"], "The Director shall notify the Auditor."))

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    summaries = [c["summary"] for c in result.changes]
    assert not any("more than one obligation" in s for s in summaries), summaries
    settled = (
        "A reviewer recorded the two clauses that changed in section 3.2 as "
        "distinct, so this is reported as a removal and an addition rather "
        "than a pairing."
    )
    # Each says what changed first and why it reads that way second — the
    # caveat follows the description rather than standing in for it, so the
    # analyst is told the obligation went before being told the bookkeeping.
    assert all(s.endswith(settled) for s in summaries), summaries
    assert [s[: -len(settled) - 1] for s in summaries] == [
        "The obligation in section 3.2 is gone.",
        "A new obligation appears in section 3.2.",
    ], summaries


def test_a_settled_clause_stops_counting_toward_its_sections_ambiguity(monkeypatch):
    """The other half of "consuming means deleting". Two unmatched old clauses
    share a section; a verdict settles one of them. The survivor is then alone
    and its removal must say so plainly — computing the tally from a
    pre-decision snapshot leaves passes 2 and 3 behaving identically while
    telling the reviewer this section was too crowded to pair."""
    _score_table(monkeypatch, {})
    old = _keyed(
        _entry("o1", ["3.2"], "The Director shall notify the Comptroller."),
        _entry("o2", ["3.2"], "Components shall report annually to the Secretary."),
    )
    new = _keyed(_entry("n1", ["9.9"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("o1", "n1"): "paired"})

    removed = [c for c in result.changes if c["kind"] == REMOVED]
    assert [c["obligation_id"] for c in removed] == ["o2"]
    assert removed[0]["summary"] == "The obligation in section 3.2 is gone."


def test_the_settled_sentence_does_not_silence_a_genuinely_ambiguous_section(
    monkeypatch,
):
    """The settled sentence must reach the settled pair and nothing else. A
    second section really does hold two changed obligations on each side, so
    the pairing rule really did decline for want of a safe guess, and that must
    still be said — a fix that suppressed AMBIGUOUS_SECTION wholesale, or
    marked more clauses settled than the verdict named, would read as green
    here while hiding the one warning this summary exists to give.

    Deliberately not a third clause inside 3.2: pass 2 reaches its `distinct`
    decline only when the section holds one changed obligation on each side, so
    a settled pair never shares its section with anything, and a fixture
    claiming otherwise would be testing an unreachable state.
    """
    _score_table(monkeypatch, {})
    old = _keyed(
        _entry("o1", ["3.2"], "The Director shall notify the Comptroller."),
        _entry("o2", ["4.1"], "Components shall report annually to the Secretary."),
        _entry("o3", ["4.1"], "The Chief shall maintain the register."),
    )
    new = _keyed(
        _entry("n1", ["3.2"], "The Director shall notify the Auditor."),
        _entry("n2", ["4.1"], "Components shall report each year to the Secretary."),
        _entry("n3", ["4.1"], "The Chief shall keep the register."),
    )

    result = _plan_changes(old, new, {("o1", "n1"): "distinct"})

    by_id = {c["obligation_id"]: c["summary"] for c in result.changes}
    assert "recorded the two clauses" in by_id["o1"]
    assert "recorded the two clauses" in by_id["n1"]
    for oid in ("o2", "o3", "n2", "n3"):
        assert "more than one obligation" in by_id[oid], oid


def test_a_distinct_decision_keyed_in_the_other_orientation_still_suppresses(
    monkeypatch,
):
    """The frozenset's whole purpose, and the one thing every forward-keyed
    test above leaves uncovered.
    `read_pairings` returns keys in the record's canonical order, but this layer
    binds whatever from/to the caller passed, so a reversed Triage run hands the
    verdict over with the ids the other way round. Keep an ordered tuple and
    both consumers agree with each other while silently agreeing on the wrong
    thing — every forward-keyed test in this file still passes."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["3.2"], "The Director shall notify the Auditor."))

    result = _plan_changes(old, new, {("n1", "o1"): "distinct"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]
    assert result.pairings_unapplied == 0


def test_an_unrecognised_verdict_is_not_applied_as_a_pairing(monkeypatch):
    """The arm the enum's docstring promised was safe. Falling through to the
    pairing arm applies any string the graph happens to hold as a `paired`
    verdict and captions the row as a human decision — putting words in a
    reviewer's mouth, which is worse than ignoring the row. `record_pairing`
    guards what it writes, but the diff reads the graph, and the graph is not
    guarded by that function."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["ENCLOSURE 2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["SECTION 4"], "Records shall be destroyed on schedule."))

    result = _plan_changes(old, new, {("o1", "n1"): "sort-of"})

    assert sorted(c["kind"] for c in result.changes) == [ADDED, REMOVED]
    # Not counted either: `pairings_unapplied` means pass 1 pre-empted a
    # verdict, and a value no writer in this codebase can produce is not that.
    assert result.pairings_unapplied == 0


def test_paired_beats_distinct_on_the_same_two_clauses_either_way_round(monkeypatch):
    """`pairing_key` is directional, so `paired` and `distinct` on the same two
    obligations are two records and both can be live. This layer resolves it —
    `paired` wins — and resolves it order-independently, because the paired arm
    never consults `distinct` and its pop leaves passes 2 and 3 nothing to
    decline. Pinned rather than left to dict iteration order."""
    _score_table(monkeypatch, {})
    old = _keyed(_entry("o1", ["3.2"], "The Director shall notify the Comptroller."))
    new = _keyed(_entry("n1", ["3.2"], "The Director shall notify the Auditor."))

    for decisions in (
        {("o1", "n1"): "paired", ("n1", "o1"): "distinct"},
        {("n1", "o1"): "distinct", ("o1", "n1"): "paired"},
    ):
        result = _plan_changes(old, new, decisions)

        assert [c["kind"] for c in result.changes] == [MODIFIED], decisions
        assert result.changes[0]["obligation_id"] == "n1", decisions
        assert result.pairings_unapplied == 0, decisions


@pytest.mark.integration
def test_diff_versions_applies_a_recorded_distinct_decision(clean_graph, database):
    """`distinct` has no end-to-end coverage otherwise — the cycle 3 test drives
    `paired` only, so the read → frozenset → pass 2 path is never exercised
    against a real graph, and neither is the sentence a reviewer actually reads.

    The fixture is `test_a_reworded_obligation_in_the_same_section_is_one_modified`'s,
    unchanged: one clause each side of section 3.2, which pass 2 pairs
    unconditionally and reports as a single MODIFIED. The verdict is the only
    difference here.
    """
    from policy_grapher.extraction.schema import obligation_id
    from policy_grapher.links.pairing import record_pairing

    _seed(clean_graph, database, version_id="v1", entries=[("3.2", NOTIFY, Modality.SHALL)])
    _seed(clean_graph, database, version_id="v2", entries=[("3.2", REPORT, Modality.SHALL)])
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=obligation_id("v1", ["3.2"], NOTIFY),
            new_id=obligation_id("v2", ["3.2"], REPORT),
            verdict="distinct",
            actor="tester",
            rationale="two duties that happen to share a section",
        )

    counts = _diff(clean_graph, database)

    assert counts == {"ADDED": 1, "REMOVED": 1, "MODIFIED": 0, "pairings_unapplied": 0}
    # The persisted sentence, not just the planned one: this is what a reviewer
    # reads, and reporting their own decision back as the ambiguity rule's
    # decline is the defect this whole path exists to avoid.
    settled = (
        "A reviewer recorded the two clauses that changed in section 3.2 as "
        "distinct, so this is reported as a removal and an addition rather than "
        "a pairing."
    )
    # The caveat now follows the description rather than replacing it, so the
    # check is that every persisted sentence carries it — the guarantee is that
    # a reviewer never reads their own decision back as the ambiguity rule's.
    persisted = {c["summary"] for c in _changes(clean_graph, database)}
    assert all(s.endswith(settled) for s in persisted), persisted
    assert not any("more than one obligation" in s for s in persisted), persisted
