"""Merging two records of one document — STORY-031, ADR-032.

Ingest has flagged near-duplicate names since STORY-003 and nothing acted on the
flag. It fires on the real corpus: `Military Standard 882E` against
`Military-Standard 882E`, and a presidential directive cited once with a
parenthetical and once without. Each is one document held as two nodes with its
inbound references divided between them.
"""

import pytest

from policy_grapher.merges import (
    MergeRefused,
    apply_merges,
    record_merge,
    record_not_duplicates,
    unresolved_duplicates,
)


def _two_externals(driver, database):
    driver.execute_query(
        "MERGE (a:Document:External {slug: 'military-standard-882e', "
        "  name: 'Military-Standard 882E'}) "
        "MERGE (b:Document:External {slug: 'military-standard-882e-alt', "
        "  name: 'Military Standard 882E'}) "
        "MERGE (c:Document {slug: 'citer-one', name: 'Citer One'}) "
        "MERGE (d:Document {slug: 'citer-two', name: 'Citer Two'}) "
        "MERGE (c)-[:REFERENCES]->(a) "
        "MERGE (d)-[:REFERENCES]->(b)",
        database_=database,
    )


@pytest.mark.integration
def test_a_merge_reunites_the_references_that_were_divided(clean_graph, database):
    """The point of the whole item: one document cited two ways is two nodes, and
    a reader browsing either sees half of what cites it."""
    _two_externals(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_merge,
            survivor="Military-Standard 882E",
            merged="Military Standard 882E",
            actor="reviewer",
        )
        session.execute_write(apply_merges)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'military-standard-882e'})<-[:REFERENCES]-(c) "
        "RETURN count(c) AS citers",
        database_=database,
    )
    assert records[0]["citers"] == 2

    gone, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'military-standard-882e-alt'}) RETURN count(d) AS n",
        database_=database,
    )
    assert gone[0]["n"] == 0


@pytest.mark.integration
def test_a_merge_survives_an_ingest_that_recreates_the_name(clean_graph, database):
    """ADR-032's reason for recording rather than editing. A manifest naming both
    spellings recreates the node; an edit would be undone silently, which is the
    failure `:LinkDecision` exists to prevent for links."""
    _two_externals(clean_graph, database)

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_merge,
            survivor="Military-Standard 882E",
            merged="Military Standard 882E",
            actor="reviewer",
        )
        session.execute_write(apply_merges)

    # An ingest brings the merged-away name back.
    clean_graph.execute_query(
        "MERGE (b:Document:External {slug: 'military-standard-882e-alt', "
        "  name: 'Military Standard 882E'}) "
        "MERGE (e:Document {slug: 'citer-three', name: 'Citer Three'}) "
        "MERGE (e)-[:REFERENCES]->(b)",
        database_=database,
    )
    with clean_graph.session(database=database) as session:
        session.execute_write(apply_merges)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {slug: 'military-standard-882e'})<-[:REFERENCES]-(c) "
        "RETURN count(c) AS citers",
        database_=database,
    )
    assert records[0]["citers"] == 3


@pytest.mark.integration
def test_a_document_carrying_text_is_refused(clean_graph, database):
    """ADR-032 takes only the case it can answer. Merging documents with editions
    raises ADR-027's questions about re-keying obligations, and refusing loudly is
    the honest boundary."""
    clean_graph.execute_query(
        "MERGE (a:Document {slug: 'keep', name: 'Keep'}) "
        "MERGE (b:Document {slug: 'lose', name: 'Lose'}) "
        "MERGE (b)-[:HAS_VERSION]->(:DocumentVersion {version_id: 'lose@2020', "
        "  checksum: 'x', source_uri: 'file:///x.pdf'})",
        database_=database,
    )

    with (
        clean_graph.session(database=database) as session,
        pytest.raises(MergeRefused) as refusal,
    ):
        session.execute_write(
            record_merge, survivor="Keep", merged="Lose", actor="reviewer"
        )

    assert "edition" in str(refusal.value).lower()


@pytest.mark.integration
def test_a_pair_ruled_different_is_not_offered_again(clean_graph, database):
    """A judgement made once is not re-asked — the same reason a rejection is
    stored beside an approval (ADR-014)."""
    _two_externals(clean_graph, database)
    flagged = [("Military-Standard 882E", "Military Standard 882E")]

    with clean_graph.session(database=database) as session:
        assert session.execute_read(unresolved_duplicates, flagged=flagged)
        session.execute_write(
            record_not_duplicates,
            first="Military-Standard 882E",
            second="Military Standard 882E",
            actor="reviewer",
        )
        assert not session.execute_read(unresolved_duplicates, flagged=flagged)


@pytest.mark.integration
def test_applying_merges_with_none_recorded_changes_nothing(clean_graph, database):
    """Called after every ingest, so the common case must be cheap and silent."""
    _two_externals(clean_graph, database)

    with clean_graph.session(database=database) as session:
        assert session.execute_write(apply_merges) == 0


@pytest.mark.integration
def test_an_ingest_re_applies_recorded_merges(clean_graph, database):
    """ADR-032's load-bearing claim, tested through the real ingest path rather
    than by calling `apply_merges` directly — the point is that a person does not
    have to remember to."""
    from pathlib import Path

    from policy_grapher.ingest import ingest_file

    samples = Path(__file__).resolve().parents[2] / "data" / "samples"
    ingest_file(clean_graph, database, "dod_policy_references_08122026.csv", samples)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.name IN "
        "['Military Standard 882E', 'Military-Standard 882E'] "
        "RETURN d.name AS name, d.slug AS slug ORDER BY name",
        database_=database,
    )
    assert len(records) == 2, "the corpus no longer contains this near-duplicate pair"
    first, second = records[0]["name"], records[1]["name"]

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_merge, survivor=second, merged=first, actor="reviewer"
        )
        session.execute_write(apply_merges)

    # Re-ingesting the same manifest recreates the merged-away name.
    ingest_file(clean_graph, database, "dod_policy_references_08122026.csv", samples)

    after, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.name IN "
        "['Military Standard 882E', 'Military-Standard 882E'] RETURN count(d) AS n",
        database_=database,
    )
    assert after[0]["n"] == 1, "the merge was undone by a re-ingest"
