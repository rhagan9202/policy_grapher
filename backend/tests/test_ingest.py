from dataclasses import replace
from pathlib import Path

import pytest
from neo4j import RoutingControl

from policy_grapher.ingest import ingest_document, ingest_file, ingest_parsed
from policy_grapher.slugs import assign_slugs, hash_suffix
from policy_grapher.sources import pdf
from policy_grapher.sources.manifest import parse_corpus

pytestmark = pytest.mark.integration

REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "samples"
SAMPLE = "dod_policy_references_08122026.csv"


def write_csv(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "corpus.csv"
    path.write_text(body, encoding="utf-8")
    return path


def count(driver, database, cypher: str) -> int:
    records, _, _ = driver.execute_query(
        cypher, database_=database, routing_=RoutingControl.READ
    )
    return records[0]["n"]


def test_small_corpus_creates_nodes_and_edges(clean_graph, database, tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\n'
        'A,"[\'B\', \'C\']",Root Reference\n'
        'B,"[\'C\']",Sub-Reference\n',
    )
    result = ingest_parsed(clean_graph, database, parse_corpus(path), path.name)

    assert result.nodes_created == 3
    assert result.relationships_created == 3
    assert count(clean_graph, database, "MATCH (d:Document) RETURN count(d) AS n") == 3


def test_external_documents_carry_the_label(
    clean_graph, database, tmp_path
):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
    )
    ingest_parsed(clean_graph, database, parse_corpus(path), path.name)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: 'B'}) "
        "RETURN d:External AS is_external",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["is_external"] is True

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: 'A'}) "
        "RETURN d:External AS is_external",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["is_external"] is False


def test_self_references_create_no_loop(clean_graph, database, tmp_path):
    path = write_csv(
        tmp_path,
        'Document Name,References,Type\nA,"[\'A\', \'B\']",Sub-Reference\n',
    )
    result = ingest_parsed(clean_graph, database, parse_corpus(path), path.name)

    assert result.self_references_skipped == 1
    loops = count(
        clean_graph,
        database,
        "MATCH (d:Document)-[:REFERENCES]->(d) RETURN count(*) AS n",
    )
    assert loops == 0


def test_a_cited_only_document_becomes_described_but_is_never_undescribed(
    clean_graph, database, tmp_path
):
    """ADR-007: promotion still happens; demotion no longer does.

    A document dropped from a later manifest keeps the DESCRIBES edge the earlier
    one gave it, so it stays non-external. That is ingest being additive, which
    SPEC-001 already claimed it was — the old demotion was the one place it wasn't.
    """
    first = tmp_path / "first.csv"
    first.write_text(
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(first), first.name)

    def fetch(name: str) -> dict:
        records, _, _ = clean_graph.execute_query(
            "MATCH (d:Document {name: $name}) RETURN d:External AS is_external",
            {"name": name},
            database_=database,
            routing_=RoutingControl.READ,
        )
        return {"is_external": records[0]["is_external"]}

    assert fetch("A") == {"is_external": False}
    assert fetch("B") == {"is_external": True}

    second = tmp_path / "second.csv"
    second.write_text(
        'Document Name,References,Type\nB,"[\'A\']",Sub-Reference\n',
        encoding="utf-8",
    )
    ingest_parsed(clean_graph, database, parse_corpus(second), second.name)

    # B is now described: promotion, unchanged from before ADR-007.
    assert fetch("B") == {"is_external": False}
    # A is no longer a row in the current manifest, but first.csv still describes it.
    assert fetch("A") == {"is_external": False}


def test_a_manifest_records_itself_as_the_source_of_its_corpus_rows(
    clean_graph, database, tmp_path
):
    path = tmp_path / "corpus.csv"
    path.write_text(
        'Document Name,References,Type\nA,"[\'B\']",Root Reference\n',
        encoding="utf-8",
    )

    ingest_parsed(clean_graph, database, parse_corpus(path), path.name)

    records, _, _ = clean_graph.execute_query(
        "MATCH (s:Source)-[:DESCRIBES]->(d:Document) "
        "RETURN s.id AS id, s.kind AS kind, collect(d.name) AS described",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["id"] == "manifest:corpus.csv"
    assert records[0]["kind"] == "manifest"
    assert records[0]["described"] == ["A"]


def test_reingesting_the_sample_corpus_creates_nothing(clean_graph, database):
    first = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    assert first.nodes_created == 438
    assert first.relationships_created == 672

    second = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    assert second.nodes_created == 0
    assert second.relationships_created == 0

    assert count(clean_graph, database, "MATCH (d:Document) RETURN count(d) AS n") == 438
    assert count(
        clean_graph, database, "MATCH ()-[r:REFERENCES]->() RETURN count(r) AS n"
    ) == 672


def test_sample_corpus_node_split_and_skips(clean_graph, database):
    result = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    assert result.self_references_skipped == 4
    assert len(result.suspected_duplicates) == 2

    corpus = count(
        clean_graph,
        database,
        "MATCH (d:Document) WHERE NOT d:External RETURN count(d) AS n",
    )
    external = count(
        clean_graph, database, "MATCH (d:External) RETURN count(d) AS n"
    )
    assert corpus == 23
    assert external == 415


def test_slugs_are_identical_across_a_reset_and_reingest(clean_graph, database):
    from policy_grapher.db import clear_graph

    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    before = {r["name"]: r["slug"] for r in records}

    clear_graph(clean_graph, database)
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    after = {r["name"]: r["slug"] for r in records}

    assert before == after
    assert len(set(after.values())) == 438


def test_the_two_corpus_slug_collisions_are_resolved_by_hash(clean_graph, database):
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    a, b = "Military Standard 882E", "Military-Standard 882E"
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE d.name IN $names RETURN d.name AS name, d.slug AS slug",
        {"names": [a, b]},
        database_=database,
        routing_=RoutingControl.READ,
    )
    slugs = {r["name"]: r["slug"] for r in records}
    assert slugs[a] == f"military-standard-882e-{hash_suffix(a)}"
    assert slugs[b] == f"military-standard-882e-{hash_suffix(b)}"


PDF_FIRST = "500001p.pdf"


def slugs_by_name(driver, database) -> dict[str, str]:
    records, _, _ = driver.execute_query(
        "MATCH (d:Document) RETURN d.name AS name, d.slug AS slug",
        database_=database,
        routing_=RoutingControl.READ,
    )
    return {r["name"]: r["slug"] for r in records}


def test_a_clean_csv_ingest_slugs_the_whole_name_set_as_before(clean_graph, database):
    """Reconciling against stored names is a no-op on an empty graph — the normal
    path, since compose auto-ingests into an empty database."""
    result = ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    assert (result.nodes_created, result.relationships_created) == (438, 672)
    expected = assign_slugs(parse_corpus(REPO_DATA / SAMPLE).all_names)
    assert slugs_by_name(clean_graph, database) == expected


def test_a_pdf_ingested_before_the_csv_does_not_block_the_manifest(clean_graph, database):
    """The manifest path reconciles against names already stored.

    `500001p.pdf` cites "Military-Standard 882E", one half of the corpus's
    contested base slug, and stores it at the bare `military-standard-882e`.
    Re-slugging the whole name set from scratch would put that name at a
    *suffixed* slug, so the manifest would try to create a second node under an
    already-taken `name` and the whole ingest would roll back on
    `document_name_unique`. Every name the PDF stored keeps its slug instead.
    """
    ingest_file(clean_graph, database, PDF_FIRST, REPO_DATA)
    before = slugs_by_name(clean_graph, database)
    assert before["Military-Standard 882E"] == "military-standard-882e"

    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    # Every name 500001p.pdf brought in is also a corpus name, so the graph lands
    # exactly where a clean CSV ingest would: 438 nodes, 672 relationships.
    assert count(clean_graph, database, "MATCH (d:Document) RETURN count(d) AS n") == 438
    assert count(
        clean_graph, database, "MATCH ()-[r:REFERENCES]->() RETURN count(r) AS n"
    ) == 672

    after = slugs_by_name(clean_graph, database)
    for name, slug in before.items():
        assert after[name] == slug, f"{name} moved from {slug} to {after[name]}"
    # The newcomer for the now-taken base takes the suffix.
    other = "Military Standard 882E"
    assert after[other] == f"military-standard-882e-{hash_suffix(other)}"
    assert len(set(after.values())) == 438


def test_the_manifest_is_still_ingestable_after_a_second_pdf(clean_graph, database):
    """500088p.pdf holds the other half of the contested pair, and cites names the
    CSV does not, so the merged graph is larger than the CSV's own 438."""
    ingest_file(clean_graph, database, "500088p.pdf", REPO_DATA)
    before = slugs_by_name(clean_graph, database)
    assert before["Military Standard 882E"] == "military-standard-882e"

    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    after = slugs_by_name(clean_graph, database)
    assert after["Military Standard 882E"] == "military-standard-882e"
    assert after["Military-Standard 882E"] == (
        f"military-standard-882e-{hash_suffix('Military-Standard 882E')}"
    )
    assert len(set(after.values())) == len(after)


def test_ingest_endpoint_returns_the_result(client_with_auth):
    response = client_with_auth.post("/ingest", json={"filename": SAMPLE})
    assert response.status_code == 200
    body = response.json()
    assert body["nodes_created"] == 438
    assert body["relationships_created"] == 672
    assert body["self_references_skipped"] == 4
    assert len(body["suspected_duplicates"]) == 2


def _outgoing_references(driver, database, slug: str) -> int:
    """How many `:REFERENCES` edges this document draws, by slug rather than by
    interpolation — no Cypher is authored from a value (ADR-017)."""
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[r:REFERENCES]->() RETURN count(r) AS n",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["n"]


def _reference_outcome(driver, database, slug: str):
    """What the graph now remembers about one document's references section.

    Returned as a pair so a caller can tell the three states apart: `(None, None)`
    is a document the parser has never seen, `(False, [])` is one it read and
    found no section in, and `(True, [...])` is one it read successfully.
    """
    records, _, _ = driver.execute_query(
        "MATCH (d:Document {slug: $slug}) "
        "RETURN d.references_section_found AS found, "
        "       d.references_unattributed AS unattributed",
        {"slug": slug},
        database_=database,
        routing_=RoutingControl.READ,
    )
    return records[0]["found"], records[0]["unattributed"]


def _parsed_as(path: Path, *, section_found: bool, unattributed=()):
    """A real extraction with its report swapped.

    The pages are the genuine ones, because `_write_document` refuses a document
    that chunks to nothing and a hand-built page would be testing the chunker
    rather than this. Only the report varies, which is the thing under test.
    """
    real = pdf.extract_document(path)
    return replace(
        real,
        report=replace(
            real.report,
            format=real.report.format if section_found else "unknown",
            section_found=section_found,
            unattributed=tuple(unattributed),
        ),
    )


def test_a_document_whose_references_section_was_not_found_says_so(
    clean_graph, database
):
    """ADR-015's shape, one level down.

    `locate_references` returns an unknown format rather than raising, so this
    document ingests successfully and draws no `REFERENCES` edges. Without the
    stored outcome a reader cannot tell that from a document that genuinely cites
    nothing, and the ingest response that once carried the difference is gone the
    moment the page reloads.
    """
    extracted = _parsed_as(REPO_DATA / PDF_FIRST, section_found=False)
    merged = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    found, unattributed = _reference_outcome(clean_graph, database, merged.slug)
    assert found is False
    assert unattributed == []


def test_a_document_whose_references_all_resolved_is_distinguishable(
    clean_graph, database
):
    """The middle state, and the one the other two are defined against."""
    extracted = _parsed_as(REPO_DATA / PDF_FIRST, section_found=True)
    merged = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    found, unattributed = _reference_outcome(clean_graph, database, merged.slug)
    assert found is True
    assert unattributed == []


def test_unresolved_reference_names_are_stored_in_full(clean_graph, database):
    """A count would say something is missing without saying enough to act on it.

    The names are what a reader needs to judge whether the gap matters — an
    unresolved public law is a different thing from an unresolved DoD issuance
    the corpus should be holding.
    """
    names = ("Public Law 99-145", "Some Memorandum Nobody Filed")
    extracted = _parsed_as(
        REPO_DATA / PDF_FIRST, section_found=True, unattributed=names
    )
    merged = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    found, unattributed = _reference_outcome(clean_graph, database, merged.slug)
    assert found is True
    assert sorted(unattributed) == sorted(names)


def test_a_document_the_parser_never_saw_reads_as_never_parsed(clean_graph, database):
    """Absent is not `false`, and this is the case that makes the difference real.

    Every document a manifest row creates, and every document that exists only
    because something cited it, has never been through the parser. Reading those
    as "parsed, no section found" would assert a negative finding about 470 of
    the 474 documents this corpus holds.
    """
    ingest_file(clean_graph, database, SAMPLE, REPO_DATA)

    found, unattributed = _reference_outcome(clean_graph, database, "dodd-5000-01")
    assert found is None
    assert unattributed is None


def test_a_later_unreadable_parse_does_not_retract_a_readable_one(
    clean_graph, database
):
    """Finding #8, settled: reference state is a fact about the document.

    No ingest path deletes a `:REFERENCES` edge (ADR-007), so the edges this
    document carries are the union of every parse of it. If the status described
    only the newest parse, re-ingesting an edition whose references section has
    become unreadable would leave the earlier parse's dependencies on the graph
    beside a flag saying nothing was read — the contradiction the accumulating
    write exists to prevent. `section_found` is therefore sticky-true.
    """
    readable = _parsed_as(REPO_DATA / PDF_FIRST, section_found=True)
    merged = ingest_document(clean_graph, database, readable, REPO_DATA / PDF_FIRST)

    edges_after_first = _outgoing_references(clean_graph, database, merged.slug)
    assert edges_after_first > 0, (
        "fixture must draw edges for the contradiction to exist"
    )

    unreadable = _parsed_as(REPO_DATA / PDF_FIRST, section_found=False)
    ingest_document(clean_graph, database, unreadable, REPO_DATA / PDF_FIRST)

    found, _ = _reference_outcome(clean_graph, database, merged.slug)
    assert found is True
    assert (
        _outgoing_references(clean_graph, database, merged.slug) == edges_after_first
    ), "the edges the flag would have contradicted are still here"


def test_a_clean_later_parse_does_not_retire_gaps_an_earlier_one_reported(
    clean_graph, database
):
    """The same rule on the other property, and the false-all-clear direction.

    A later parse that resolves everything must not silently drop the entries an
    earlier parse could not attribute, because that earlier parse's edges remain.
    Dropping them would report a document as fully resolved when part of its
    reference set came from a read that had gaps — ADR-015's most dangerous
    output. Over-reporting a gap is a person's to close; under-reporting one is
    not recoverable by a reader who is never told.
    """
    first = ("Some Memorandum Nobody Filed", "Public Law 99-145")
    earlier = _parsed_as(REPO_DATA / PDF_FIRST, section_found=True, unattributed=first)
    merged = ingest_document(clean_graph, database, earlier, REPO_DATA / PDF_FIRST)

    later = _parsed_as(REPO_DATA / PDF_FIRST, section_found=True, unattributed=())
    ingest_document(clean_graph, database, later, REPO_DATA / PDF_FIRST)

    _, unattributed = _reference_outcome(clean_graph, database, merged.slug)
    assert sorted(unattributed) == sorted(first)


def test_a_new_parse_adds_its_gaps_without_duplicating_the_standing_ones(
    clean_graph, database
):
    """Union, not append — and re-reading the same bytes changes nothing.

    Accumulation must not turn a repeated ingest into a growing list of the same
    entry: an ingest that would rewrite nothing rewrites nothing (ADR-042). The
    second ingest here repeats one entry and introduces one, so a plain
    concatenation shows the repeated entry twice and this test fails.
    """
    earlier = _parsed_as(
        REPO_DATA / PDF_FIRST, section_found=True, unattributed=("Entry A", "Entry B")
    )
    merged = ingest_document(clean_graph, database, earlier, REPO_DATA / PDF_FIRST)

    later = _parsed_as(
        REPO_DATA / PDF_FIRST, section_found=True, unattributed=("Entry B", "Entry C")
    )
    ingest_document(clean_graph, database, later, REPO_DATA / PDF_FIRST)

    _, unattributed = _reference_outcome(clean_graph, database, merged.slug)
    assert sorted(unattributed) == ["Entry A", "Entry B", "Entry C"]
    assert len(unattributed) == len(set(unattributed)), "an entry was recorded twice"
