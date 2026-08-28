"""Rebuilding the derived layer must not cost a human decision.

This is the test file that makes "rebuildable overlay" a fact rather than an
intention. Chunks, obligations, proposals and `IMPLEMENTS` edges are all derived
and all dropped here; `:LinkDecision` is canonical and must come through
untouched, with every approval re-promoted and every rejection still suppressed.
If that is not true, phase 5 must not start.
"""

import re
from pathlib import Path

import pytest

from policy_grapher import chunking
from policy_grapher.changes.diff import diff_versions
from policy_grapher.chunking import Chunk, chunk_pages
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.ingest import ingest_file
from policy_grapher.links.decisions import record_decision
from policy_grapher.links.rebuild import (
    ExtractionFailed,
    MissingSourceError,
    rebuild_derived,
    states_no_duty,
)

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"

# One org-tier issuance and one higher-tier one, chosen because their real text
# produces enough lexically overlapping duties for the weak proposer to find
# something to review.
ORG_FILE = "514301p.pdf"
HIGHER_FILE = "500001p_2003.pdf"

MODAL_SENTENCE = re.compile(r"[^.]*?\b(?:shall|must)\b[^.]*\.", re.IGNORECASE)


class ModalSentenceExtractor:
    """A deterministic stand-in for a model, over real policy text.

    Not good extraction — it takes any sentence containing "shall" or "must".
    That is enough, and the point: these tests are about whether a rebuild
    preserves decisions, and a real model would make them slow, non-reproducible
    and unrunnable without a model server. `skip` lets a test simulate an
    extractor change that stops producing one particular obligation.
    """

    adapter_id = "modal-sentence-stub"

    def __init__(self, *, skip: str | None = None) -> None:
        self._skip = skip

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop=None,
    ) -> list[ExtractedObligation]:
        found = []
        for sentence in MODAL_SENTENCE.findall(chunk_text):
            statement = " ".join(sentence.split())
            if self._skip is not None and self._skip == statement:
                continue
            found.append(
                ExtractedObligation(
                    statement=statement,
                    modality=(
                        Modality.SHALL
                        if "shall" in statement.casefold()
                        else Modality.MUST
                    ),
                    actor=None,
                    deadline=None,
                    conditions=None,
                    confidence=0.5,
                )
            )
        return found


def _ingest(driver, database, filename: str) -> str:
    result = ingest_file(driver, database, filename, SAMPLES)
    records, _, _ = driver.execute_query(
        "MATCH (:Document {slug: $slug})-[:HAS_VERSION]->(v:DocumentVersion) "
        "RETURN v.version_id AS id",
        {"slug": result.document.slug},
        database_=database,
    )
    return records[0]["id"]


def _proposals(driver, database) -> list[tuple[str, str]]:
    records, _, _ = driver.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS_PROPOSED]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target "
        "ORDER BY source, target",
        database_=database,
    )
    return [(r["source"], r["target"]) for r in records]


def _implements(driver, database) -> set[tuple[str, str]]:
    records, _, _ = driver.execute_query(
        "MATCH (a:Obligation)-[:IMPLEMENTS]->(b:Obligation) "
        "RETURN a.obligation_id AS source, b.obligation_id AS target",
        database_=database,
    )
    return {(r["source"], r["target"]) for r in records}


def _decisions(driver, database) -> set[tuple[str, str, str]]:
    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) "
        "RETURN d.key AS key, d.verdict AS verdict, d.actor AS actor",
        database_=database,
    )
    return {(r["key"], r["verdict"], r["actor"]) for r in records}


def _obligation_ids(driver, database) -> set[str]:
    records, _, _ = driver.execute_query(
        "MATCH (o:Obligation) RETURN o.obligation_id AS id", database_=database
    )
    return {r["id"] for r in records}


def _chunk_ids(driver, database) -> set[str]:
    records, _, _ = driver.execute_query(
        "MATCH (c:Chunk) RETURN c.chunk_id AS id", database_=database
    )
    return {r["id"] for r in records}


def _obligation_ids_for(driver, database, version_id: str) -> set[str]:
    """One edition's obligation ids — scoped, unlike `_obligation_ids`, because
    a rekey test rebuilds only one of the two editions in `reviewed_graph` and
    must not let the untouched edition's stable ids mask the rebuilt one's."""
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $version_id})-[:MANDATES]->(o:Obligation) "
        "RETURN o.obligation_id AS id",
        {"version_id": version_id},
        database_=database,
    )
    return {r["id"] for r in records}


def _decision_rows(driver, database) -> list[dict]:
    """Full decision rows, including the obligation ids a repoint moves — unlike
    `_decisions`, which reports only `key`, and a moved key alone does not show
    which pair it now points at."""
    records, _, _ = driver.execute_query(
        "MATCH (d:LinkDecision) "
        "RETURN d.actor AS actor, d.verdict AS verdict, "
        "d.source_obligation_id AS source_id, d.target_obligation_id AS target_id",
        database_=database,
    )
    return [dict(r) for r in records]


@pytest.fixture
def reviewed_graph(clean_graph, database):
    """Two issuances ingested, extracted, and linked — with one proposal approved
    and one rejected. The state every test below rebuilds from."""
    higher = _ingest(clean_graph, database, HIGHER_FILE)
    org = _ingest(clean_graph, database, ORG_FILE)
    extractor = ModalSentenceExtractor()

    rebuild_derived(
        clean_graph, database, version_id=higher, extractor=extractor
    )
    report = rebuild_derived(
        clean_graph,
        database,
        version_id=org,
        extractor=extractor,
        candidate_version_ids=[higher],
        proposer="lexical-v1",
    )

    proposals = _proposals(clean_graph, database)
    assert len(proposals) >= 2, (
        "the fixtures must yield at least two proposals for this suite to mean "
        f"anything; got {len(proposals)}"
    )
    approved, rejected = proposals[0], proposals[1]

    with clean_graph.session(database=database) as session:
        session.execute_write(
            record_decision,
            source_id=approved[0],
            target_id=approved[1],
            verdict="approve",
            actor="alice",
            rationale="Discharges the higher duty.",
        )
        session.execute_write(
            record_decision,
            source_id=rejected[0],
            target_id=rejected[1],
            verdict="reject",
            actor="bob",
            rationale="Different subject matter.",
        )
    rebuild_derived(
        clean_graph,
        database,
        version_id=org,
        extractor=extractor,
        candidate_version_ids=[higher],
        proposer="lexical-v1",
    )

    return {
        "org": org,
        "higher": higher,
        "extractor": extractor,
        "approved": approved,
        "rejected": rejected,
        "report": report,
    }


@pytest.mark.integration
def test_a_rebuild_preserves_every_human_decision(reviewed_graph, clean_graph, database):
    """Drop the derived layer, re-extract, replay. Approvals and rejections both
    survive. If this fails, the overlay is not rebuildable and phase 5 must not
    start."""
    before_implements = _implements(clean_graph, database)
    before_decisions = _decisions(clean_graph, database)
    assert reviewed_graph["approved"] in before_implements
    assert reviewed_graph["rejected"] not in before_implements

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    assert _implements(clean_graph, database) == before_implements
    assert _decisions(clean_graph, database) == before_decisions
    assert reviewed_graph["rejected"] not in _implements(clean_graph, database)
    assert report["promoted"] == 1
    assert report["suppressed"] == 1
    assert report["unpromotable"] == 0


@pytest.mark.integration
def test_a_rebuild_reproduces_the_same_chunks_and_obligations(
    reviewed_graph, clean_graph, database
):
    """Identity is content- and structure-derived, so a rebuild over unchanged
    input must land on exactly the same ids — which is what lets a decision key
    still find its obligations afterwards."""
    before_chunks = _chunk_ids(clean_graph, database)
    before_obligations = _obligation_ids(clean_graph, database)

    rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    assert _chunk_ids(clean_graph, database) == before_chunks
    assert _obligation_ids(clean_graph, database) == before_obligations


@pytest.mark.integration
def test_a_rebuild_carries_an_approval_across_a_full_rekey(
    reviewed_graph, clean_graph, database, monkeypatch
):
    """Commit 79d40e9 changed some chunks' `section_path`, which re-keys their
    obligations and would strand a `:LinkDecision` — unless commit 89d0622's
    `repoint_decisions` is actually wired into `rebuild_derived`, not merely
    correct in isolation (the unit tests in test_links.py already cover that).

    Forcing `section_heading` to suffix every heading it finds is a strictly
    harder case than the real change: it re-keys *every* chunk and obligation
    of the rebuilt edition, not just the back matter. `chunk_pages` resolves
    `section_heading` as a module-global name at call time, so patching the
    module attribute is what makes this take.
    """
    org = reviewed_graph["org"]
    higher = reviewed_graph["higher"]
    approved = reviewed_graph["approved"]
    rejected = reviewed_graph["rejected"]

    before_implements = _implements(clean_graph, database)
    before_org_obligations = _obligation_ids_for(clean_graph, database, org)
    assert approved in before_implements
    assert rejected not in before_implements

    original_section_heading = chunking.section_heading

    def rekeyed_section_heading(line: str) -> str | None:
        heading = original_section_heading(line)
        return f"{heading}-REKEYED" if heading is not None else None

    monkeypatch.setattr(chunking, "section_heading", rekeyed_section_heading)

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=org,
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[higher],
        proposer="lexical-v1",
    )

    after_org_obligations = _obligation_ids_for(clean_graph, database, org)
    assert after_org_obligations, "the rebuild produced no obligations"
    # The whole point of this test: if the rekey did not actually change any
    # id, everything below would pass against a no-op and prove nothing.
    assert after_org_obligations != before_org_obligations, (
        "forcing every heading to change did not change any obligation id"
    )
    assert approved[0] not in after_org_obligations, (
        "the approved obligation's own id must have moved"
    )

    decisions = _decision_rows(clean_graph, database)
    alice = next(d for d in decisions if d["actor"] == "alice")
    bob = next(d for d in decisions if d["actor"] == "bob")
    assert alice["verdict"] == "approve"
    assert bob["verdict"] == "reject"
    assert alice["source_id"] != approved[0], "alice's decision was not repointed"
    assert alice["target_id"] == approved[1], "the untouched edition must not move"
    assert bob["target_id"] == rejected[1]

    after_implements = _implements(clean_graph, database)
    assert (alice["source_id"], alice["target_id"]) in after_implements, (
        "the approval did not survive the rekey"
    )
    assert (bob["source_id"], bob["target_id"]) not in after_implements, (
        "a repair that resurrected a rejection is worse than one that lost an approval"
    )
    assert approved not in after_implements, "the old ids must be gone, not merely joined"

    assert report["decisions_repointed"] > 0
    assert report["unpromotable"] == 0


@pytest.mark.integration
def test_an_obligation_that_stops_being_extracted_leaves_its_decision_unpromotable(
    reviewed_graph, clean_graph, database
):
    """An extractor change that no longer produces one side of an approved link.
    The decision is still a fact a human established, so it stays recorded — but
    the graph cannot express it, and the rebuild has to report that rather than
    return a healthy-looking count."""
    source_id = reviewed_graph["approved"][0]
    records, _, _ = clean_graph.execute_query(
        "MATCH (o:Obligation {obligation_id: $id}) RETURN o.statement AS statement",
        {"id": source_id},
        database_=database,
    )
    statement = records[0]["statement"]
    before_decisions = _decisions(clean_graph, database)

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=ModalSentenceExtractor(skip=statement),
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    assert report["unpromotable"] == 1
    assert report["promoted"] == 0
    assert reviewed_graph["approved"] not in _implements(clean_graph, database)
    # The decision itself is untouched — same key, same verdict, same actor.
    assert _decisions(clean_graph, database) == before_decisions
    assert len(before_decisions) == 2


@pytest.mark.integration
def test_a_rebuild_leaves_the_canonical_layer_untouched(
    reviewed_graph, clean_graph, database
):
    """Documents, editions and provenance are canonical: a rebuild reads them and
    writes none of them."""
    query = (
        "MATCH (d:Document) WITH count(d) AS documents "
        "MATCH (v:DocumentVersion) WITH documents, count(v) AS versions "
        "MATCH (s:Source) WITH documents, versions, count(s) AS sources "
        "MATCH (dec:LinkDecision) "
        "RETURN documents, versions, sources, count(dec) AS decisions"
    )
    before, _, _ = clean_graph.execute_query(query, database_=database)

    rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    after, _, _ = clean_graph.execute_query(query, database_=database)
    assert dict(after[0]) == dict(before[0])
    assert before[0]["documents"] > 0 and before[0]["decisions"] == 2


@pytest.mark.integration
def test_a_rebuild_fails_loudly_when_the_source_document_is_gone(
    clean_graph, database, tmp_path
):
    """Re-chunking needs the original file, not the stored chunk text. If it is
    not where source_uri says, the rebuild must stop — dropping the derived layer
    and then finding nothing to replace it with would delete a version's whole
    text and report success."""
    missing = tmp_path / "vanished.pdf"
    clean_graph.execute_query(
        "CREATE (d:Document {slug: 'gone', name: 'GONE'})-[:HAS_VERSION]->"
        "(:DocumentVersion {version_id: 'v', checksum: 'x', source_uri: $uri})",
        {"uri": f"file://{missing}"},
        database_=database,
    )

    with pytest.raises(MissingSourceError, match="vanished.pdf"):
        rebuild_derived(
            clean_graph, database, version_id="v", extractor=ModalSentenceExtractor()
        )


@pytest.mark.integration
def test_a_rebuild_of_an_unknown_version_fails_loudly(clean_graph, database):
    with pytest.raises(MissingSourceError, match="no-such-version"):
        rebuild_derived(
            clean_graph,
            database,
            version_id="no-such-version",
            extractor=ModalSentenceExtractor(),
        )


@pytest.mark.integration
def test_a_rebuild_takes_the_changes_that_referenced_it(
    reviewed_graph, clean_graph, database
):
    """A :Change AFFECTS an obligation, and a rebuild drops obligations. Left
    alone, the change would survive pointing at nothing — visible to a reviewer
    and impossible to trace back to a clause."""
    with clean_graph.session(database=database) as session:
        session.execute_write(
            diff_versions,
            from_version_id=reviewed_graph["higher"],
            to_version_id=reviewed_graph["org"],
        )
    before, _, _ = clean_graph.execute_query(
        "MATCH (c:Change) RETURN count(c) AS total", database_=database
    )
    assert before[0]["total"] > 0, "the fixture must actually produce changes"

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        candidate_version_ids=[reviewed_graph["higher"]],
        proposer="lexical-v1",
    )

    assert report["changes_dropped"] == before[0]["total"]
    after, _, _ = clean_graph.execute_query(
        "MATCH (c:Change) RETURN count(c) AS total", database_=database
    )
    assert after[0]["total"] == 0


@pytest.mark.integration
def test_a_rebuild_reports_progress_chunk_by_chunk(reviewed_graph, clean_graph, database):
    """A run over a real edition takes minutes with a real model, and the caller
    is watching. Progress is reported per chunk, ending at the chunk count."""
    seen: list[tuple[int, int]] = []

    rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen, "no progress was reported"
    totals = {total for _, total in seen}
    assert len(totals) == 1, f"the total changed mid-run: {totals}"
    total = totals.pop()
    assert [done for done, _ in seen] == list(range(1, total + 1))


@pytest.mark.integration
def test_a_rebuild_without_a_progress_callback_still_works(
    reviewed_graph, clean_graph, database
):
    """The callback is optional — every existing caller passes nothing."""
    counts = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=reviewed_graph["extractor"],
    )

    assert counts["chunks_written"] > 0


# --- one bad item does not destroy the run (STORY-057) ------------------------


class OneBadChunkExtractor:
    """A model that returns something unparseable on the Nth chunk it sees.

    Not hypothetical. Sprint 4's walkthrough ran DoDD 5000.01 through
    `llama3.1:8b` and the model answered `modality: null` for one clause, which
    `ExtractedObligation` rejects — correctly, the enum is closed on purpose so
    an adapter cannot invent a binding level. `LocalExtractor` re-raises that as
    ValueError, and the run died at chunk 5 of 38.
    """

    adapter_id = "one-bad-chunk-stub"

    def __init__(self, *, fail_on: int, inner=None) -> None:
        self._fail_on = fail_on
        self._inner = inner or ModalSentenceExtractor()
        self.seen = 0

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop=None,
    ):
        self.seen += 1
        if self.seen == self._fail_on:
            raise ValueError(
                "model output did not match the obligation schema: modality was null"
            )
        return self._inner.extract(chunk_text, section_path=section_path)


class AlwaysBadExtractor:
    adapter_id = "always-bad-stub"

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop=None,
    ):
        raise ValueError("model output did not match the obligation schema")


@pytest.mark.integration
def test_one_unparseable_chunk_does_not_fail_the_whole_rebuild(
    reviewed_graph, clean_graph, database
):
    extractor = OneBadChunkExtractor(fail_on=1)

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=extractor,
    )

    assert report["chunks_written"] > 0, "the run produced nothing"
    assert extractor.seen > 1, "extraction stopped at the failing chunk"


@pytest.mark.integration
def test_a_rebuild_counts_the_chunks_it_rejected(reviewed_graph, clean_graph, database):
    """A count of zero must be distinguishable from 'nothing was checked'."""
    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=OneBadChunkExtractor(fail_on=1),
    )

    assert report["chunks_rejected"] == 1

    clean = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=ModalSentenceExtractor(),
    )
    assert clean["chunks_rejected"] == 0


@pytest.mark.integration
def test_a_rebuild_in_which_every_chunk_failed_does_not_report_success(
    reviewed_graph, clean_graph, database
):
    """Tolerating one bad item must not turn a wholly broken model into a green run."""
    with pytest.raises(ExtractionFailed):
        rebuild_derived(
            clean_graph,
            database,
            version_id=reviewed_graph["org"],
            extractor=AlwaysBadExtractor(),
        )


@pytest.mark.integration
def test_a_rebuild_reports_why_it_rejected_a_chunk(reviewed_graph, clean_graph, database):
    """STORY-057 asked for the count *and why*, and for rejected items to be
    visible without reading container logs. The count alone says an edition is
    incomplete without saying what is missing from it — which is the shape of
    answer ADR-023 exists to avoid, one level down.
    """
    seen: list[tuple[str, str]] = []

    report = rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=OneBadChunkExtractor(fail_on=1),
        on_rejection=lambda chunk_id, reason: seen.append((chunk_id, reason)),
    )

    assert report["chunks_rejected"] == 1
    assert len(seen) == 1
    chunk_id, reason = seen[0]
    assert chunk_id, "the rejection does not say which chunk it was"
    assert "modality" in reason, f"the reason does not describe the failure: {reason!r}"


@pytest.mark.integration
def test_a_clean_rebuild_reports_no_rejections(reviewed_graph, clean_graph, database):
    seen: list[tuple[str, str]] = []

    rebuild_derived(
        clean_graph,
        database,
        version_id=reviewed_graph["org"],
        extractor=ModalSentenceExtractor(),
        on_rejection=lambda chunk_id, reason: seen.append((chunk_id, reason)),
    )

    assert seen == []


class _DropsOneItem:
    """Returns one good obligation and reports one dropped, the way ADR-030 says
    an adapter should when a single item fails validation."""

    adapter_id = "drops-one"

    def extract(
        self,
        chunk_text: str,
        *,
        section_path: list[str],
        section_title: str | None = None,
        on_drop=None,
    ):
        if on_drop is not None:
            on_drop("model output did not match the obligation schema: modality")
        return [
            ExtractedObligation(
                statement="Components shall comply with this issuance.",
                modality=Modality.SHALL,
                actor=None,
                deadline=None,
                conditions=None,
                confidence=0.9,
            )
        ]


@pytest.mark.integration
def test_a_rebuild_counts_the_items_it_dropped(clean_graph, database):
    """ADR-030 makes the count part of the decision, not an extra.

    Dropping an item quietly is the shape ADR-023's loud-failure argument warns
    about: a run that stops is hard to ignore and a number in a report is easy.
    Without this the screen loses the only way it has left to say an edition is
    incomplete, which is what STORY-057 was for.
    """
    version_id = _ingest(clean_graph, database, ORG_FILE)

    counts = rebuild_derived(
        clean_graph,
        database,
        version_id=version_id,
        extractor=_DropsOneItem(),
    )

    assert counts["items_dropped"] > 0
    # And the chunk still produced its surviving obligation, which is the whole
    # point of moving the boundary.
    assert counts["obligations_written"] > 0
    assert counts["chunks_rejected"] == 0


# --- STORY-098: front matter is not offered to the extractor -------------------


def test_a_contents_page_is_not_offered_to_the_extractor():
    """A page of dot leaders states no duty, and that is knowable without a
    ninety-second model call."""
    chunk = Chunk(
        chunk_id="c1",
        text=(
            "1.1.  APPLICABILITY. ...................................... 4\n"
            "1.2.  POLICY. ............................................. 5\n"
            "1.3.  RESPONSIBILITIES. ................................... 6\n"
        ),
        page=2,
        section_path=["(preamble)"],
        ordinal=0,
    )

    assert states_no_duty(chunk) == "table of contents"


def test_the_references_section_is_not_offered_to_the_extractor():
    """`sources/pdf.py` already parses it for the reference graph, so asking a
    model for duties in it is pure waste. Found by the title the document wrote,
    which `chunking.BACK_MATTER` already opens as its own section."""
    chunk = Chunk(
        chunk_id="c2",
        text='(a) DoD Directive 5144.02, "DoD Chief Information Officer," 2014.',
        page=3,
        section_path=["ENCLOSURE 1"],
        ordinal=0,
        section_title="REFERENCES",
    )

    assert states_no_duty(chunk) == "references section"


def test_ordinary_policy_text_is_offered_to_the_extractor():
    """The predicate must say no far more often than yes, or it becomes the
    silent cause of a document that yields nothing."""
    chunk = Chunk(
        chunk_id="c3",
        text="The Director shall notify the Comptroller within 30 days.",
        page=4,
        section_path=["SECTION 2", "2.1"],
        ordinal=0,
        section_title="RESPONSIBILITIES",
    )

    assert states_no_duty(chunk) is None


def test_an_empty_chunk_is_not_reported_as_a_contents_page():
    """A chunk with no non-blank lines has no dot leaders to be a majority of."""
    chunk = Chunk(chunk_id="c4", text="\n\n", page=1, section_path=["1"], ordinal=0)

    assert states_no_duty(chunk) is None


def test_over_the_real_corpus_the_skip_never_touches_a_responsibilities_chunk():
    """The property that matters, asserted over the documents rather than over a
    fixture: whatever this skips, it must never skip the section ADR-033 exists
    to read.

    Not asserted per document, deliberately. DoDD 5000.01's 2003 edition skips
    nothing and that is correct — it has zero dot-leader lines and no standalone
    REFERENCES heading, because it uses the legacy inline "References: (a) ..."
    form on its cover. STORY-098 says in as many words that a document with no
    contents page skips nothing, so a per-document floor would be asserting the
    opposite of the requirement.
    """
    from policy_grapher.sources.pdf import pages_of

    total_skipped = 0
    for path in sorted(Path("../data/samples").glob("*.pdf")):
        chunks = chunk_pages(pages_of(path), version_id="v")
        skipped = [c for c in chunks if states_no_duty(c) is not None]
        total_skipped += len(skipped)
        for chunk in skipped:
            assert not (
                chunk.section_title and "RESPONSIBILIT" in chunk.section_title
            ), f"{path.name}: skipped a responsibilities chunk: {chunk.text[:80]!r}"

    assert total_skipped, "the predicate skipped nothing anywhere in the corpus"


def test_a_references_section_opened_as_its_own_heading_is_skipped():
    """`chunking.BACK_MATTER` opens REFERENCES as a section in its own right, so
    it arrives in `section_path` and never as a title — a bare heading line has
    no title after it to parse. Measured across the corpus, checking only the
    title skipped zero references sections, which is how this was found.
    """
    chunk = Chunk(
        chunk_id="c5",
        text='(a) DoD Directive 5144.02, "DoD Chief Information Officer," 2014.',
        page=3,
        section_path=["REFERENCES"],
        ordinal=0,
        section_title=None,
    )

    assert states_no_duty(chunk) == "references section"
