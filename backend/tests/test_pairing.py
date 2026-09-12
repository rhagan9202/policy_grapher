"""The canonical `:PairingDecision` path: key, verdicts, edition-scoped reads."""

import pytest
from neo4j import RoutingControl

from policy_grapher.links.pairing import (
    CrossDocumentPair,
    count_stranded_pairings,
    pairing_key,
    pairing_lock_key,
    read_pairings,
    read_settled,
    record_pairing,
)

# --- the key and the verdict vocabulary (no graph needed) ---------------------


def test_the_pairing_key_is_directional():
    """The properties say which end is old. A symmetric key would let a
    mis-ordered write replace a well-ordered verdict it does not match."""
    assert pairing_key("a", "b") != pairing_key("b", "a")


def test_the_pairing_key_is_stable():
    assert pairing_key("a", "b") == pairing_key("a", "b")


def test_an_unknown_verdict_is_refused_before_anything_is_written():
    """The vocabulary is closed for `decisions.Verdict`'s reason: the diff
    branches on the value, and one it does not know would be silently
    ignored — a settled pair the diff keeps re-asking about. Validation
    precedes the write, so `tx` is never touched and no graph is needed."""
    with pytest.raises(ValueError, match="verdict"):
        record_pairing(
            None, old_id="a", new_id="b", verdict="maybe", actor="x", rationale=""
        )


# --- recording and reading against a real graph -------------------------------


def _seed_edition(driver, database, *, version_id, obligation_ids, slug="doc"):
    """An edition MANDATES-ing obligations under caller-chosen ids.

    Seeded directly rather than through chunking and extraction: these tests
    are about the `:MANDATES` topology the reads scope through, and the ids are
    the fixture's vocabulary — deriving them from statements would only obscure
    which obligation each assertion names.

    `slug` defaults so that every edition here belongs to one document, which is
    what the pairing question is asked within; only the cross-document refusal's
    tests pass a second one.
    """
    driver.execute_query(
        "MERGE (d:Document {slug: $slug, name: $slug}) "
        "MERGE (d)-[:HAS_VERSION]->(v:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'}) "
        "WITH v UNWIND $ids AS id "
        "MERGE (o:Obligation {obligation_id: id}) "
        "MERGE (v)-[:MANDATES]->(o)",
        {"vid": version_id, "ids": obligation_ids, "slug": slug},
        database_=database,
    )


def _record(driver, database, *, old, new, verdict, actor="alice", rationale="r"):
    with driver.session(database=database) as session:
        session.execute_write(
            record_pairing,
            old_id=old,
            new_id=new,
            verdict=verdict,
            actor=actor,
            rationale=rationale,
        )


def _read(driver, database, *, from_version_id, to_version_id):
    with driver.session(database=database) as session:
        return session.execute_read(
            read_pairings,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
        )


@pytest.mark.integration
def test_a_recorded_pairing_is_read_back_under_either_edition_order(
    clean_graph, database
):
    """Triage accepts arbitrary direction, so the read must accept the editions
    in either role — while the returned keys stay as stored, older→newer."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["old-clause"]
    )
    _seed_edition(
        clean_graph, database, version_id="e2022", obligation_ids=["new-clause"]
    )
    _record(clean_graph, database, old="old-clause", new="new-clause", verdict="paired")

    forward = _read(clean_graph, database, from_version_id="e2018", to_version_id="e2022")
    backward = _read(clean_graph, database, from_version_id="e2022", to_version_id="e2018")

    assert forward == {("old-clause", "new-clause"): "paired"}
    assert backward == forward


@pytest.mark.integration
def test_re_recording_the_same_pair_replaces_the_verdict_in_place(
    clean_graph, database
):
    """One current verdict per ordered pair, never two contradictory records
    for the diff to choose between. No seeding: `record_pairing` binds no
    editions — admissibility is the route's business — so the replace is
    observable on the bare node."""
    _record(clean_graph, database, old="a", new="b", verdict="paired")
    _record(clean_graph, database, old="a", new="b", verdict="distinct", actor="bob")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:PairingDecision) RETURN count(d) AS total, "
        "collect(d.verdict) AS verdicts, collect(d.actor) AS actors",
        database_=database,
    )
    assert records[0]["total"] == 1
    assert records[0]["verdicts"] == ["distinct"]
    assert records[0]["actors"] == ["bob"]


@pytest.mark.integration
def test_a_neighbouring_pairs_verdict_does_not_leak_into_this_read(
    clean_graph, database
):
    """A middle edition belongs to two pairs, so scoping by "touches either
    edition" would leak the adjacent diff's verdicts into this one. Both
    obligations must sit in the two named editions, one in each — which also
    keeps out a decision recorded inside a single edition."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["a1", "a2"]
    )
    _seed_edition(clean_graph, database, version_id="e2020", obligation_ids=["b1"])
    _seed_edition(clean_graph, database, version_id="e2022", obligation_ids=["c1"])
    _record(clean_graph, database, old="a1", new="b1", verdict="paired")
    _record(clean_graph, database, old="b1", new="c1", verdict="distinct")
    # Recordable at this layer — `record_pairing` refuses only a pair drawn from
    # two documents, and these two clauses share one — so the read has to be the
    # thing that keeps it out of both adjacent pairs' diffs.
    _record(clean_graph, database, old="a1", new="a2", verdict="distinct")

    first = _read(clean_graph, database, from_version_id="e2018", to_version_id="e2020")
    second = _read(clean_graph, database, from_version_id="e2020", to_version_id="e2022")

    assert first == {("a1", "b1"): "paired"}
    assert second == {("b1", "c1"): "distinct"}


@pytest.mark.integration
def test_settled_pairs_carry_their_actor_and_respect_the_same_scope(
    clean_graph, database
):
    """The queue lists settled pairs so a reviewer can reach one to undo it;
    who settled it is part of what they are undoing."""
    _seed_edition(clean_graph, database, version_id="e2018", obligation_ids=["a1"])
    _seed_edition(clean_graph, database, version_id="e2020", obligation_ids=["b1"])
    _seed_edition(clean_graph, database, version_id="e2022", obligation_ids=["c1"])
    _record(clean_graph, database, old="a1", new="b1", verdict="paired", actor="alice")
    _record(clean_graph, database, old="b1", new="c1", verdict="distinct", actor="bob")

    with clean_graph.session(database=database) as session:
        settled = session.execute_read(
            read_settled, from_version_id="e2018", to_version_id="e2020"
        )

    assert settled == [
        {"old_id": "a1", "new_id": "b1", "verdict": "paired", "actor": "alice"}
    ]


@pytest.mark.integration
def test_a_pairing_whose_obligation_is_gone_is_counted_stranded(
    clean_graph, database
):
    """After a re-extraction the decision is still a fact a human established,
    but the graph cannot express it, and a rebuild must say so rather than
    report only what it applied."""
    _seed_edition(
        clean_graph, database, version_id="e2018", obligation_ids=["old-clause"]
    )
    _seed_edition(
        clean_graph, database, version_id="e2022", obligation_ids=["new-clause"]
    )
    _record(clean_graph, database, old="old-clause", new="new-clause", verdict="paired")

    with clean_graph.session(database=database) as session:
        before = session.execute_read(count_stranded_pairings)
    clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: 'new-clause'}) DETACH DELETE o",
        database_=database,
    )
    with clean_graph.session(database=database) as session:
        after = session.execute_read(count_stranded_pairings)

    assert before == 0
    assert after == 1


# --- the cross-document refusal -----------------------------------------------


@pytest.mark.integration
def test_a_cross_document_pair_is_refused_by_record_pairing(clean_graph, database):
    """"Is the newer clause the older one reworded?" is a question about one
    instrument's editions. Between two instruments the question is
    implementation, and its verdict belongs on a `:LinkDecision` — a
    `:PairingDecision` recorded here would be read back by `read_pairings`
    whenever a diff happened to name both editions, and applied as a rewording
    of a clause in another document.

    The refusal lives in the recorder and not only in the route for
    `record_decision`'s reason: a rule one caller enforces is a rule only that
    caller obeys.
    """
    _seed_edition(
        clean_graph, database, version_id="a@2018", obligation_ids=["ours"], slug="a"
    )
    _seed_edition(
        clean_graph, database, version_id="b@2020", obligation_ids=["theirs"], slug="b"
    )

    with pytest.raises(CrossDocumentPair, match="implements") as refusal:
        _record(clean_graph, database, old="ours", new="theirs", verdict="paired")

    # Both slugs, quoted. Unquoted, "a" and "b" are satisfied by the refusal's
    # own prose — every phrasing of it contains both letters somewhere — so the
    # assertion would pin nothing at all. The ids in the message are content
    # hashes in production, so naming the two instruments is what makes the
    # refusal actionable.
    assert "'a'" in str(refusal.value)
    assert "'b'" in str(refusal.value)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:PairingDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 0


@pytest.mark.integration
def test_a_pairing_on_ids_the_graph_cannot_resolve_still_records(
    clean_graph, database
):
    """A `:PairingDecision` outlives its obligations by design — that is what
    `repoint_decisions` repairs and `count_stranded_pairings` counts — so a
    verdict stranded by a re-extraction must stay recordable and re-recordable.

    This is the assertion that fixes the *direction* of the guard. A refusal
    phrased "I cannot see one document holding both" rather than "I can see two
    documents and they differ" passes the test above and fails here, and the
    difference is every stranded verdict in the graph becoming unwritable.
    """
    _record(clean_graph, database, old="gone-a", new="gone-b", verdict="paired")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:PairingDecision) RETURN d.verdict AS verdict", database_=database
    )
    assert [record["verdict"] for record in records] == ["paired"]


@pytest.mark.integration
def test_a_pairing_with_only_one_side_resolvable_still_records(
    clean_graph, database
):
    """Half-stranded, which is the shape a re-extraction actually produces: one
    clause of the pair is reproduced under a new id and the other is not, which
    is why `STRANDED` joins its two absence checks with `OR` and not `AND`.

    Not covered by the both-gone case above, and the difference is a whole
    implementation: a guard phrased "the obligations I can see belong to one
    document" admits the both-gone pair — it sees none — and refuses this one,
    because the single surviving side belongs to exactly one document. Both
    orientations, so a guard anchored on only the old or only the new side is
    caught too.
    """
    _seed_edition(clean_graph, database, version_id="e2018", obligation_ids=["alive"])

    _record(clean_graph, database, old="alive", new="gone", verdict="paired")
    _record(clean_graph, database, old="gone", new="alive", verdict="distinct")

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:PairingDecision) RETURN count(d) AS total", database_=database
    )
    assert records[0]["total"] == 2


def test_the_pair_lock_key_is_one_per_edition_pair():
    """Every caller settling a pair between two editions must compute the same
    key, or they take different locks and serialise nothing. Distinct edition
    pairs must get distinct keys, or settling between one pair blocks settling
    between an unrelated one."""
    assert pairing_lock_key("d@2018", "d@2020") == pairing_lock_key(
        "d@2018", "d@2020"
    )
    assert pairing_lock_key("d@2018", "d@2020") != pairing_lock_key(
        "d@2020", "d@2022"
    )
    # Not `pairing_key`'s value for the same two strings. The two keys index
    # different labels so a collision could not merge a lock into a decision,
    # but a shared value would make either one's appearance in a log or an
    # export ambiguous about which it came from.
    assert pairing_lock_key("a", "b") != pairing_key("a", "b")


@pytest.mark.integration
def test_the_pairing_lock_key_constraint_exists(driver, database):
    """Not hygiene — half the locking mechanism. `ACQUIRE_PAIR_LOCK` is a bare
    MERGE, and a MERGE racing itself creates a second node for the same key
    unless a uniqueness constraint makes it lock the index entry first. Two
    transactions then hold two different lock nodes, block on neither, and the
    two-live-paired race the lock exists to close is open again. Measured: with
    the constraint dropped, the concurrency test in `test_pairings.py` fails on
    every run with the lock still in place."""
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert "pairing_lock_key_unique" in set(records[0]["names"])


@pytest.mark.integration
def test_the_pairing_decision_key_constraint_exists(driver, database):
    """`record_pairing`'s MERGE holds one node per key only while the key is
    unique; without the constraint a concurrent writer can slip a second node
    under the same key, and the repoint path's collision screening assumes
    there is exactly one."""
    records, _, _ = driver.execute_query(
        "SHOW CONSTRAINTS YIELD name RETURN collect(name) AS names",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert "pairing_decision_key_unique" in set(records[0]["names"])
