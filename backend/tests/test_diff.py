"""Diffing two editions of one instrument into changes a reviewer can read."""

import pytest

from policy_grapher.changes.diff import content_key, diff_versions, drop_changes
from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.extraction.schema import ExtractedObligation, Modality
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

    assert counts == {"ADDED": 1, "REMOVED": 0, "MODIFIED": 0}
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

    assert counts == {"ADDED": 0, "REMOVED": 1, "MODIFIED": 0}
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

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0}
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

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 1}


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

    assert counts == {"ADDED": 2, "REMOVED": 2, "MODIFIED": 0}
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

    assert counts == {"ADDED": 0, "REMOVED": 0, "MODIFIED": 0}
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
