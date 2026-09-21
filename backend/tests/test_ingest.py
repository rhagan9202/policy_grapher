import re
from dataclasses import replace
from pathlib import Path

import pypdf
import pytest
from neo4j import RoutingControl

from policy_grapher import chunking
from policy_grapher.builds import record_build_finished, record_build_started
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.graph import build_graph
from policy_grapher.ingest import ingest_document, ingest_file, ingest_parsed
from policy_grapher.links.decisions import record_decision, replay_decisions
from policy_grapher.slugs import assign_slugs, hash_suffix
from policy_grapher.sources import pdf
from policy_grapher.sources.manifest import parse_corpus
from policy_grapher.versions import VersionConflictError

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
# A different edition of the same issuance: same document, different date.
PDF_OTHER_EDITION = "500001p_2020.pdf"
# The one sample whose real text states duties, so a derived layer built over
# it is a real one rather than an empty structure that would survive anything.
PDF_WITH_DUTIES = "500001p_2003.pdf"
# A second issuance that also states duties, so a reviewed link has two
# documents to span — within one document the relationship is pairing, not
# implementation, and the decision recorder refuses it.
PDF_WITH_DUTIES_TOO = "514301p.pdf"


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


# ---------------------------------------------------------------------------
# U7 / ADR-042. An ingest that would rewrite nothing rewrites nothing.
#
# The checksum covers the bytes going in; the pipeline stamp covers the
# machinery that turns them into chunks. Only both together answer the question
# a re-ingest has to ask before discarding a derived layer: would running again
# produce the chunks that are already there?
# ---------------------------------------------------------------------------


class ModalSentenceStub:
    """A deterministic stand-in for a model: any sentence stating a duty.

    Defined once here rather than inside each test that needs it. A real
    extractor would make these tests slow, non-reproducible and unrunnable
    without a model server, and what they are actually about is whether an
    unchanged re-ingest leaves an existing derived layer alone.
    """

    adapter_id = "modal-sentence-stub"
    cache_variant = ""

    def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
        found = []
        for sentence in re.findall(
            r"[^.]*?\b(?:shall|must)\b[^.]*\.", chunk_text, re.IGNORECASE
        ):
            statement = " ".join(sentence.split())
            found.append(
                ExtractedObligation(
                    statement=statement,
                    # Read off the sentence rather than fixed: the schema checks
                    # the stated modality against the words, and a mismatch
                    # rejects the whole chunk rather than the one item.
                    modality=(
                        Modality.SHALL
                        if "shall" in statement.casefold()
                        else Modality.MUST
                    ),
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=1.0,
                )
            )
        return found


def _chunk_texts(driver, database, version_id: str) -> list[str]:
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $v})-[:HAS_CHUNK]->(c:Chunk) "
        "RETURN c.text AS text ORDER BY c.ordinal",
        v=version_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return [r["text"] for r in records]


def test_an_unchanged_re_ingest_writes_no_chunks_and_says_so(clean_graph, database):
    """The case the whole unit exists for: the same file, added twice.

    Re-adding is routine — ADR-007 makes ingest additive precisely so it is safe
    — and the map is about to make adding a document the product's most
    prominent action. The most likely re-ingest is therefore somebody adding the
    same file again, which today costs every derived thing built on that edition
    and reports a successful write while doing it.
    """
    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert first.chunks_written is not None and first.chunks_written > 0

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    # None, not 0. A zero count is a claim that a write happened and produced
    # nothing, which is the reading ADR-042 forbids.
    assert again.chunks_written is None
    assert again.version_id == first.version_id
    # And the chunks it declined to rewrite are still the ones standing.
    assert _chunk_texts(clean_graph, database, first.version_id)


def _counts(driver, database, version_id: str) -> dict:
    """What an unchanged re-ingest must leave exactly as it found it."""
    records, _, _ = driver.execute_query(
        """
        MATCH (v:DocumentVersion {version_id: $v})
        OPTIONAL MATCH (v)-[:HAS_CHUNK]->(c:Chunk)
        OPTIONAL MATCH (v)-[:MANDATES]->(o:Obligation)
        OPTIONAL MATCH (o)-[i:IMPLEMENTS]->()
        RETURN count(DISTINCT c) AS chunks,
               count(DISTINCT o) AS obligations,
               count(DISTINCT i) AS implements,
               v.build_state AS build_state
        """,
        v=version_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    return dict(records[0])


def _approve_one_link(driver, database, *, source_version: str, target_version: str) -> None:
    """Give an edition one reviewed link: the thing AE5 is most about keeping.

    `replay_decisions` is the only writer of `:IMPLEMENTS` anywhere, and it only
    promotes pairs a person has verdicted — so a fixture that builds obligations
    alone has nothing to lose here, and a before/after comparison of the
    IMPLEMENTS count would hold at 0 == 0 whatever the code did.

    The two obligations come from different documents because that is what an
    implementation link is: within one document the relationship is pairing, and
    `record_decision` refuses the pair outright.
    """
    def first_obligation(version_id: str) -> str:
        records, _, _ = driver.execute_query(
            "MATCH (:DocumentVersion {version_id: $v})-[:MANDATES]->(o:Obligation) "
            "RETURN o.obligation_id AS id ORDER BY o.obligation_id LIMIT 1",
            v=version_id,
            database_=database,
            routing_=RoutingControl.READ,
        )
        assert records, f"fixture built no obligation on {version_id}"
        return records[0]["id"]

    with driver.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id=first_obligation(source_version),
            target_id=first_obligation(target_version),
            verdict="approve",
            actor="test-reviewer",
            rationale="seeded so the reviewed-link count is not trivially zero",
        )
        session.execute_write(replay_decisions)


def test_an_unchanged_re_ingest_keeps_the_derived_layer_and_its_verdicts(
    clean_graph, database
):
    """AE5, and the reason ADR-042 exists.

    An hour of extraction and every human verdict resting on it, against a
    reader who added the same file twice. The counts are asserted whole rather
    than one at a time: the failure this guards drops chunks with a DETACH
    DELETE, which takes the anchors with it and leaves obligations standing but
    unreadable, a state where any single count still looks right.
    """
    from policy_grapher.links.rebuild import rebuild_derived

    source = REPO_DATA / PDF_WITH_DUTIES
    extracted = pdf.extract_document(source)
    first = ingest_document(clean_graph, database, extracted, source)
    counts = rebuild_derived(
        clean_graph, database, version_id=first.version_id,
        extractor=ModalSentenceStub(),
    )
    # The build record is written by the job that drives a rebuild, not by
    # `rebuild_derived` itself, so the fixture records one the way that job
    # does. Otherwise "the build record stands" would be a claim about a field
    # that was never set.
    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_build_started,
            version_id=first.version_id,
            run_id="test-run",
            extractor_adapter=ModalSentenceStub.adapter_id,
            embedder_adapter="none",
        )
        session.execute_write(
            record_build_finished,
            version_id=first.version_id,
            run_id="test-run",
            counts=counts,
        )
    # A real approved link, not just obligations. `_counts` compares IMPLEMENTS
    # before and after, and without a recorded verdict that comparison is 0 == 0
    # — it would hold whether or not the skip preserves reviewed work, which is
    # the half of AE5 most expensive to lose.
    higher = REPO_DATA / PDF_WITH_DUTIES_TOO
    implemented = ingest_document(
        clean_graph, database, pdf.extract_document(higher), higher
    )
    rebuild_derived(
        clean_graph, database, version_id=implemented.version_id,
        extractor=ModalSentenceStub(),
    )
    _approve_one_link(
        clean_graph, database,
        source_version=first.version_id, target_version=implemented.version_id,
    )

    before = _counts(clean_graph, database, first.version_id)
    assert before["obligations"] > 0, "fixture built nothing to protect"
    assert before["implements"] > 0, "fixture recorded no verdict to protect"
    assert before["build_state"] is not None

    again = ingest_document(clean_graph, database, extracted, source)

    assert again.chunks_written is None
    assert _counts(clean_graph, database, first.version_id) == before


def test_a_skipped_re_ingest_leaves_the_reported_fidelity_tier_unchanged(
    clean_graph, database
):
    """The unit's own verification, read from the surface that states it.

    The tier is derived at request time from what the graph holds, so it is the
    honest end-to-end check on whether anything was lost: an edition whose
    obligations were discarded reports a lower tier than the same edition with
    them, and no amount of "nothing was written" in a response body changes
    that.
    """
    from policy_grapher.links.rebuild import rebuild_derived

    source = REPO_DATA / PDF_WITH_DUTIES
    extracted = pdf.extract_document(source)
    merged = ingest_document(clean_graph, database, extracted, source)
    rebuild_derived(
        clean_graph, database, version_id=merged.version_id,
        extractor=ModalSentenceStub(),
    )

    def tier() -> int:
        drawn = build_graph(clean_graph, database, focus=merged.slug, depth=1)
        return next(n.fidelity_tier for n in drawn.nodes if n.id == merged.slug)

    before = tier()
    assert before >= 4, "precondition: the edition must have obligations to lose"

    again = ingest_document(clean_graph, database, extracted, source)

    assert again.chunks_written is None
    assert tier() == before


def test_an_upgrade_of_the_extraction_dependency_forces_the_rewrite(
    clean_graph, database, monkeypatch
):
    """The stage nobody edits, and the reason the stamp is derived.

    `pypdf` is floored with no upper bound, so an upgrade changes the text this
    pipeline reads with no code change in this repository. A stamp naming only
    the chunker would let that pass as unchanged and leave obligations anchored
    to text the pipeline no longer produces.
    """
    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert first.chunks_written is not None

    monkeypatch.setattr(pypdf, "__version__", f"{pypdf.__version__}+upgraded")

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert again.chunks_written == first.chunks_written


def test_a_chunker_change_forces_the_rewrite(
    clean_graph, database, tmp_path, monkeypatch
):
    """The hazard ADR-039 was written for, which this narrowing must not lose.

    The mutated chunker is a throwaway copy the stage module is pointed at, not
    the tracked file edited in place: `_stage_digest` resolves the path through
    `module.__file__` on every call and the stamp is uncached, so redirecting it
    exercises the same property with nothing in the repository to restore if
    this process is killed partway.
    """
    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    mutated = tmp_path / "chunking.py"
    mutated.write_bytes(
        Path(chunking.__file__).read_bytes() + b"\n# a chunker change\n"
    )
    monkeypatch.setattr(chunking, "__file__", str(mutated))

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert again.chunks_written == first.chunks_written


@pytest.mark.parametrize("stage", ["sources.pdf", "chunks"])
def test_every_stage_between_the_bytes_and_the_chunks_moves_the_stamp(
    clean_graph, database, tmp_path, monkeypatch, stage
):
    """The chunker is not the only stage, and it is the only one covered above.

    `_STAGES` names three modules, and dropping any one of them leaves a real
    hole: an edition re-chunked by a changed extractor or a changed writer would
    read as current and keep obligations anchored to text the pipeline no longer
    produces. Each is exercised the same way the chunker is — by moving the
    module's `__file__` at a mutated copy — so a future edit that shortened the
    tuple fails here rather than silently narrowing what the stamp notices.
    """
    from policy_grapher import chunks as chunks_module
    from policy_grapher.sources import pdf as pdf_module

    module = {"sources.pdf": pdf_module, "chunks": chunks_module}[stage]

    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert first.chunks_written is not None

    mutated = tmp_path / "stage.py"
    mutated.write_bytes(Path(module.__file__).read_bytes() + b"\n# a stage change\n")
    monkeypatch.setattr(module, "__file__", str(mutated))

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert again.chunks_written == first.chunks_written


def test_another_edition_of_the_same_issuance_writes_its_own_chunks(
    clean_graph, database
):
    """A changed file is a different edition, and the skip must not reach it.

    Note which comparison actually decides this. Two files claiming the *same*
    issuance and date never arrive here at all: `merge_version` refuses them
    with a conflict (R14/AE8), so by the time the currency check runs the stored
    checksum already equals the presented one. A file with a different date
    resolves to a different edition, which has no chunks of its own to leave
    standing.
    """
    first_doc = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, first_doc, REPO_DATA / PDF_FIRST)

    other = REPO_DATA / PDF_OTHER_EDITION
    second = ingest_document(
        clean_graph, database, pdf.extract_document(other), other
    )

    assert second.version_id != first.version_id
    assert second.chunks_written is not None and second.chunks_written > 0


def test_the_skip_never_stands_in_for_a_conflicting_edition(clean_graph, database):
    """The bytes half of ADR-042's condition, where it is actually enforced.

    Two files claiming the same issuance and date must be refused, not quietly
    skipped. The skip and the refusal answer superficially similar questions,
    and a skip that swallowed a conflict would turn R14's loud refusal into
    silence, which is the one outcome worse than either.
    """
    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    # The same issuance and effective date, presented by a different file. The
    # checksum is taken from the bytes on disk, so the second call reads another
    # file's bytes while claiming this document's identity.
    with pytest.raises(VersionConflictError):
        ingest_document(
            clean_graph, database, extracted, REPO_DATA / PDF_OTHER_EDITION
        )


def test_an_edition_with_no_recorded_stamp_is_rewritten(clean_graph, database):
    """Editions written before the stamp existed behave exactly as they do today.

    The safe direction for an unknown is the old behaviour, not the new one: an
    absent stamp must read as a mismatch rather than as "nothing to compare, so
    nothing to do".
    """
    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    clean_graph.execute_query(
        "MATCH (v:DocumentVersion {version_id: $v}) REMOVE v.pipeline_stamp",
        v=first.version_id,
        database_=database,
    )

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert again.chunks_written == first.chunks_written


def test_an_edition_re_chunked_by_a_rebuild_is_skipped_by_the_next_re_ingest(
    clean_graph, database
):
    """The door this ADR opened, closed.

    A rebuild re-reads the source and rewrites chunks too. Stamping only in
    ingest would leave every rebuilt edition reading as stale, so the next
    unchanged re-add would discard exactly the derived work the rebuild had
    just spent an hour producing.
    """
    from policy_grapher.links.rebuild import rebuild_derived

    class _Nothing:
        adapter_id = "test-null"
        cache_variant = ""

        def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
            return []

    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)

    clean_graph.execute_query(
        "MATCH (v:DocumentVersion {version_id: $v}) REMOVE v.pipeline_stamp",
        v=first.version_id,
        database_=database,
    )
    rebuild_derived(
        clean_graph, database, version_id=first.version_id, extractor=_Nothing()
    )

    again = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    assert again.chunks_written is None


def test_a_rebuild_stamps_the_pipeline_that_produced_its_chunks(
    clean_graph, database, tmp_path, monkeypatch
):
    """The stamp names the pipeline the chunks came from, not the one that
    happened to be installed when the transaction committed.

    A rebuild reads the source and chunks it outside the write transaction,
    because that is the slow phase — minutes, with a real extractor. Reading the
    stamp inside the transaction instead would let a stage's source change in
    that window and record chunks produced by one pipeline as the work of
    another, which a later ingest would read as current and decline to rebuild.
    Simulated by moving a stage's source during extraction itself.
    """
    from policy_grapher.links.rebuild import rebuild_derived
    from policy_grapher.pipeline import pipeline_stamp

    class _Nothing:
        adapter_id = "test-null"
        cache_variant = ""

        def extract(self, chunk_text, *, section_path, section_title=None, on_drop=None):
            return []

    extracted = pdf.extract_document(REPO_DATA / PDF_FIRST)
    first = ingest_document(clean_graph, database, extracted, REPO_DATA / PDF_FIRST)
    before_stamp = pipeline_stamp()

    real_extract = pdf.extract_document

    def extract_and_move_the_pipeline(path):
        mutated = tmp_path / "chunking.py"
        mutated.write_bytes(
            Path(chunking.__file__).read_bytes() + b"\n# changed mid-extraction\n"
        )
        monkeypatch.setattr(chunking, "__file__", str(mutated))
        return real_extract(path)

    monkeypatch.setattr(pdf, "extract_document", extract_and_move_the_pipeline)
    rebuild_derived(
        clean_graph, database, version_id=first.version_id, extractor=_Nothing()
    )
    assert pipeline_stamp() != before_stamp, "precondition: the pipeline did move"

    records, _, _ = clean_graph.execute_query(
        "MATCH (v:DocumentVersion {version_id: $v}) RETURN v.pipeline_stamp AS stamp",
        v=first.version_id,
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records[0]["stamp"] == before_stamp


def test_a_skipped_re_ingest_still_re_reads_the_references_section(
    clean_graph, database
):
    """What the skip must not cover.

    A document whose references section could not be read once would otherwise
    be frozen in that state permanently: the parse that could finally read it
    would be skipped along with the chunks, and the map would keep asserting an
    unknown that had since become knowable.
    """
    unreadable = _parsed_as(REPO_DATA / PDF_FIRST, section_found=False)
    first = ingest_document(clean_graph, database, unreadable, REPO_DATA / PDF_FIRST)
    found, _ = _reference_outcome(clean_graph, database, first.slug)
    assert found is False

    readable = _parsed_as(
        REPO_DATA / PDF_FIRST, section_found=True, unattributed=("Public Law 99-145",)
    )
    again = ingest_document(clean_graph, database, readable, REPO_DATA / PDF_FIRST)

    # The chunks were left standing, and the reference outcome was still read.
    assert again.chunks_written is None
    found, unattributed = _reference_outcome(clean_graph, database, first.slug)
    assert found is True
    assert unattributed == ["Public Law 99-145"]


def test_a_skipped_re_ingest_still_labels_the_documents_it_newly_cites(
    clean_graph, database
):
    """The other half of what sits outside the skip.

    A parse that finally reads a references section creates the documents it
    names, and a document nothing describes is an external reference: the graph
    holds its name, not its text. That label is applied by the same refresh the
    write path runs, so a skip that returned early before reaching it would
    leave the new documents unlabelled, and the map would draw them as corpus
    documents it had ingested.
    """
    bare = replace(pdf.extract_document(REPO_DATA / PDF_FIRST), references=())
    first = ingest_document(clean_graph, database, bare, REPO_DATA / PDF_FIRST)
    assert first.chunks_written is not None

    cites = replace(bare, references=("Some Memorandum Nobody Filed",))
    again = ingest_document(clean_graph, database, cites, REPO_DATA / PDF_FIRST)

    assert again.chunks_written is None, "precondition: this re-ingest was skipped"
    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document {name: $name}) RETURN 'External' IN labels(d) AS external",
        name="Some Memorandum Nobody Filed",
        database_=database,
        routing_=RoutingControl.READ,
    )
    assert records and records[0]["external"] is True


def test_the_api_reports_an_unchanged_re_ingest_as_its_own_outcome(client_with_auth):
    """ADR-042's actual contract, over HTTP.

    Every other test here calls `ingest_document`, which returns a dataclass
    with no `outcome` at all — so the field the whole decision record exists to
    add, and the one a reader's screen branches on, was decided by a ternary no
    backend test ever evaluated. Inverting it would have left both suites green
    while the API reported a skipped rewrite as a successful write.
    """
    first = client_with_auth.post("/ingest", json={"filename": PDF_FIRST})
    assert first.status_code == 200, first.text
    assert first.json()["outcome"] == "written"
    assert first.json()["chunks_written"] > 0

    again = client_with_auth.post("/ingest", json={"filename": PDF_FIRST})
    assert again.status_code == 200, again.text
    assert again.json()["outcome"] == "unchanged"
    # null, not 0: a zero would claim a write that produced nothing.
    assert again.json()["chunks_written"] is None
    assert again.json()["version_id"] == first.json()["version_id"]
