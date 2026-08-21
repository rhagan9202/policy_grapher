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

from policy_grapher.changes.diff import diff_versions
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.ingest import ingest_file
from policy_grapher.links.decisions import record_decision
from policy_grapher.links.rebuild import MissingSourceError, rebuild_derived

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
        self, chunk_text: str, *, section_path: list[str]
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
