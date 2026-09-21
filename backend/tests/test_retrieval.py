"""Retrieval fuses three signals. Each test here is about one of them earning its place."""

import pytest
from support import STAMP, FakeEmbedder, local_or_skip

from policy_grapher.chunking import chunk_pages
from policy_grapher.chunks import write_chunks
from policy_grapher.embedding import embed_chunks
from policy_grapher.embedding.null import NullEmbedder
from policy_grapher.embedding.schema import EmbeddingModelMismatch
from policy_grapher.extraction.schema import ExtractedObligation, Modality
from policy_grapher.obligations import write_obligations
from policy_grapher.retrieval.hybrid import retrieve


def _seed(driver, database, *, version_id, doc_name, text, statement=None):
    """One document, one edition, one chunk, optionally one obligation."""
    driver.execute_query(
        "MERGE (d:Document {slug: $slug}) SET d.name = $name "
        "MERGE (d)-[:HAS_VERSION]->(:DocumentVersion {version_id: $vid, "
        "checksum: $vid, source_uri: 'file:///d.pdf'})",
        {"slug": version_id, "name": doc_name, "vid": version_id},
        database_=database,
    )
    chunk = chunk_pages([f"1.1. A.\n{text}\n"], version_id=version_id)[-1]
    with driver.session(database=database) as session:
        session.execute_write(write_chunks, version_id=version_id, chunks=[chunk], pipeline_stamp=STAMP)
        if statement is not None:
            session.execute_write(
                write_obligations,
                version_id=version_id,
                chunk_id=chunk.chunk_id,
                section_path=chunk.section_path,
                obligations=[
                    ExtractedObligation(
                        statement=statement,
                        modality=Modality.MUST,
                        actor=None,
                        deadline=None,
                        conditions=None,
                        confidence=0.9,
                    )
                ],
            )
    return chunk


def _obligation_id(driver, database, version_id):
    records, _, _ = driver.execute_query(
        "MATCH (:DocumentVersion {version_id: $vid})-[:MANDATES]->(o:Obligation) "
        "RETURN o.obligation_id AS id",
        {"vid": version_id},
        database_=database,
    )
    return records[0]["id"]


def _by_id(results):
    return {r.chunk_id: r for r in results}


# --- the lexical leg ----------------------------------------------------------


@pytest.mark.integration
def test_an_exact_designator_is_found_by_the_lexical_leg(clean_graph, database):
    """Designators are lexical objects. Embeddings handle them badly, which is
    the entire reason this leg exists alongside the vector one."""
    chunk = _seed(
        clean_graph, database, version_id="v", doc_name="ORG 1.0",
        text="Components shall comply with DoDI 5000.88 when assessing risk.",
    )

    results = retrieve(
        clean_graph, database, query='"DoDI 5000.88"', embedder=NullEmbedder()
    )

    found = _by_id(results)
    assert chunk.chunk_id in found
    assert "fulltext" in found[chunk.chunk_id].signals


@pytest.mark.integration
def test_results_carry_their_citation(clean_graph, database):
    """Every hit has to be quotable, or an answer built on it is unsourced."""
    _seed(
        clean_graph, database, version_id="v", doc_name="DoDI 5000.88",
        text="Components shall comply with DoDI 5000.88.",
    )

    result = retrieve(
        clean_graph, database, query='"DoDI 5000.88"', embedder=NullEmbedder()
    )[0]

    assert result.document == "DoDI 5000.88"
    assert result.section_path == ["1.1"]
    assert result.page == 1
    assert result.text.strip()


@pytest.mark.integration
def test_an_empty_corpus_returns_nothing_rather_than_raising(clean_graph, database):
    assert retrieve(clean_graph, database, query="anything", embedder=NullEmbedder()) == []


@pytest.mark.integration
def test_a_query_of_punctuation_is_survivable(clean_graph, database):
    """The query reaches a Lucene parser. Unescaped, `s.14(2)` or a stray `~`
    throws, and a search box is exactly where such a string arrives."""
    _seed(
        clean_graph, database, version_id="v", doc_name="ORG 1.0",
        text="Components shall comply with section 14(2).",
    )

    assert retrieve(
        clean_graph, database, query="s.14(2) AND ~^ !!", embedder=NullEmbedder()
    ) is not None


# --- the vector leg -----------------------------------------------------------


@pytest.mark.integration
def test_a_paraphrase_is_found_by_the_vector_leg(clean_graph, database):
    """No word in common with the passage. The lexical leg cannot see it."""
    embedder = local_or_skip()
    chunk = _seed(
        clean_graph, database, version_id="v", doc_name="ORG 1.0",
        text="Personnel shall safeguard classified material at all times.",
    )
    embed_chunks(clean_graph, database, version_id="v", embedder=embedder)

    results = retrieve(
        clean_graph, database, query="protecting secret documents", embedder=embedder
    )

    found = _by_id(results)
    assert chunk.chunk_id in found, [r.text for r in results]
    assert "vector" in found[chunk.chunk_id].signals


@pytest.mark.integration
def test_a_paraphrase_is_reached_but_not_grounded(clean_graph, database):
    """The vector leg's whole purpose, and the limit of what it proves.

    The passage comes back — that is `test_a_paraphrase_is_found_by_the_vector_leg`
    above — but nothing about the question's wording reached it, so it is not
    evidence that the corpus addresses the question. A vector index ranks every
    chunk it holds against any input, so it always has a top hit; `zzqqxx
    wibblefrotz` gets one too. The caller decides what to say over a passage;
    this decides what the passage is.
    """
    embedder = local_or_skip()
    chunk = _seed(
        clean_graph, database, version_id="v", doc_name="ORG 1.0",
        text="Personnel shall safeguard classified material at all times.",
    )
    embed_chunks(clean_graph, database, version_id="v", embedder=embedder)

    found = _by_id(
        retrieve(
            clean_graph, database, query="protecting secret documents",
            embedder=embedder,
        )
    )

    assert found[chunk.chunk_id].signals == ("vector",)
    assert found[chunk.chunk_id].grounded is False


@pytest.mark.integration
def test_a_graph_hop_inherits_the_grounding_of_its_seed(clean_graph, database):
    """A hop is as grounded as where it started.

    Our clause shares no wording with the question and is reachable only across a
    human-approved IMPLEMENTS edge — but the passage that seeded the hop *was*
    matched lexically, so the question's words did reach ours, by one link. The
    check is made on the hop rather than on the returned rows because reciprocal
    rank fusion can drop the seed out of the result while keeping what it
    reached, which would otherwise make a properly linked answer look ungrounded.
    """
    _seed(
        clean_graph, database, version_id="higher", doc_name="DoDI 5000.88",
        text="Components must document the cybersecurity strategy.",
        statement="Components must document the cybersecurity strategy.",
    )
    ours = _seed(
        clean_graph, database, version_id="ours", doc_name="ORG 1.0",
        text="Widget calibration must be performed quarterly by the technician.",
        statement="Widget calibration must be performed quarterly by the technician.",
    )
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $ours}) "
        "MATCH (b:Obligation {obligation_id: $higher}) MERGE (a)-[:IMPLEMENTS]->(b)",
        {
            "ours": _obligation_id(clean_graph, database, "ours"),
            "higher": _obligation_id(clean_graph, database, "higher"),
        },
        database_=database,
    )

    found = _by_id(
        retrieve(
            clean_graph, database, query="cybersecurity strategy",
            embedder=NullEmbedder(),
        )
    )

    assert found[ours.chunk_id].signals == ("graph",)
    assert found[ours.chunk_id].grounded is True


@pytest.mark.integration
def test_a_hop_from_an_unanchored_seed_is_not_grounded(clean_graph, database):
    """The negative case, and the one the rule exists for.

    The edge is human-approved either way. What differs is why retrieval arrived
    at it: here the seed was found by embedding similarity alone, so the hop
    inherits nothing. Measured before the rule was per-passage, `zzqqxx
    wibblefrotz` came back `{'graph': 5, 'vector': 5}` — five hops along real
    links, no lexical hit anywhere, presented as what the corpus states.

    The question shares no word with either passage, so the lexical leg returns
    nothing and the seed can only have come from the vector leg.
    """
    embedder = local_or_skip()
    _seed(
        clean_graph, database, version_id="higher", doc_name="DoDI 5000.88",
        text="Personnel must safeguard classified material at all times.",
        statement="Personnel must safeguard classified material at all times.",
    )
    ours = _seed(
        clean_graph, database, version_id="ours", doc_name="ORG 1.0",
        text="Widget calibration must be performed quarterly by the technician.",
        statement="Widget calibration must be performed quarterly by the technician.",
    )
    # Only the seed is embedded. Embedding ours too let the vector leg find it
    # directly, so the hop was never exercised — the guard below caught that.
    embed_chunks(clean_graph, database, version_id="higher", embedder=embedder)
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $ours}) "
        "MATCH (b:Obligation {obligation_id: $higher}) MERGE (a)-[:IMPLEMENTS]->(b)",
        {
            "ours": _obligation_id(clean_graph, database, "ours"),
            "higher": _obligation_id(clean_graph, database, "higher"),
        },
        database_=database,
    )

    found = _by_id(
        retrieve(
            clean_graph, database, query="protecting secret documents",
            embedder=embedder,
        )
    )

    # Guard against passing for the wrong reason: the hop has to have happened.
    assert ours.chunk_id in found, [r.text for r in found.values()]
    assert "graph" in found[ours.chunk_id].signals
    assert found[ours.chunk_id].grounded is False
    # And the seed it came from is itself ungrounded, which is why.
    assert all(not hit.grounded for hit in found.values())


@pytest.mark.integration
def test_a_query_embedded_by_the_wrong_model_is_refused(clean_graph, database):
    """Searching a model-A index with a model-B query vector is the same silent
    failure as writing one, and it must be refused at the same volume."""
    _seed(clean_graph, database, version_id="v", doc_name="ORG 1.0", text="Some text.")
    embed_chunks(clean_graph, database, version_id="v", embedder=FakeEmbedder())

    with pytest.raises(EmbeddingModelMismatch):
        retrieve(
            clean_graph, database, query="anything",
            embedder=FakeEmbedder(model_id="fake-b"),
        )


# --- the graph leg ------------------------------------------------------------


@pytest.mark.integration
def test_the_graph_leg_reaches_what_no_other_leg_can(clean_graph, database):
    """The test that proves the graph leg earns its place, and the difference
    between graph RAG and RAG standing next to a graph.

    Our clause shares no vocabulary with the question. It is reachable only
    because a human approved an IMPLEMENTS edge from it to the higher-level
    obligation the question is actually about.
    """
    _seed(
        clean_graph, database, version_id="higher", doc_name="DoDI 5000.88",
        text="Components must document the cybersecurity strategy.",
        statement="Components must document the cybersecurity strategy.",
    )
    ours = _seed(
        clean_graph, database, version_id="ours", doc_name="ORG 1.0",
        text="Widget calibration must be performed quarterly by the technician.",
        statement="Widget calibration must be performed quarterly by the technician.",
    )
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $ours}) "
        "MATCH (b:Obligation {obligation_id: $higher}) MERGE (a)-[:IMPLEMENTS]->(b)",
        {
            "ours": _obligation_id(clean_graph, database, "ours"),
            "higher": _obligation_id(clean_graph, database, "higher"),
        },
        database_=database,
    )

    results = retrieve(
        clean_graph, database, query="cybersecurity strategy", embedder=NullEmbedder()
    )

    found = _by_id(results)
    assert ours.chunk_id in found, [r.text for r in results]
    # Only the graph leg found it — which is the assertion that neither the
    # vector nor the lexical leg could have.
    assert found[ours.chunk_id].signals == ("graph",)


@pytest.mark.integration
def test_the_graph_leg_reaches_in_both_directions(clean_graph, database):
    """A question about our clause should surface the higher duty it discharges,
    just as a question about the higher duty surfaces ours."""
    _seed(
        clean_graph, database, version_id="higher", doc_name="DoDI 5000.88",
        text="Widget calibration must be performed quarterly by the technician.",
        statement="Widget calibration must be performed quarterly by the technician.",
    )
    higher_chunk_id = _seed(
        clean_graph, database, version_id="ours", doc_name="ORG 1.0",
        text="Components must document the cybersecurity strategy.",
        statement="Components must document the cybersecurity strategy.",
    )
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $a}) MATCH (b:Obligation {obligation_id: $b}) "
        "MERGE (a)-[:IMPLEMENTS]->(b)",
        {
            "a": _obligation_id(clean_graph, database, "higher"),
            "b": _obligation_id(clean_graph, database, "ours"),
        },
        database_=database,
    )

    results = retrieve(
        clean_graph, database, query="cybersecurity strategy", embedder=NullEmbedder()
    )

    assert higher_chunk_id.chunk_id in _by_id(results)
    assert len(results) == 2


@pytest.mark.integration
def test_an_unreviewed_proposal_is_not_a_graph_hop(clean_graph, database):
    """IMPLEMENTS only, never IMPLEMENTS_PROPOSED — the same invariant triage
    keeps. An unreviewed guess must not pull a passage into an answer."""
    _seed(
        clean_graph, database, version_id="higher", doc_name="DoDI 5000.88",
        text="Components must document the cybersecurity strategy.",
        statement="Components must document the cybersecurity strategy.",
    )
    ours = _seed(
        clean_graph, database, version_id="ours", doc_name="ORG 1.0",
        text="Widget calibration must be performed quarterly by the technician.",
        statement="Widget calibration must be performed quarterly by the technician.",
    )
    clean_graph.execute_query(
        "MATCH (a:Obligation {obligation_id: $ours}) "
        "MATCH (b:Obligation {obligation_id: $higher}) "
        "MERGE (a)-[:IMPLEMENTS_PROPOSED]->(b)",
        {
            "ours": _obligation_id(clean_graph, database, "ours"),
            "higher": _obligation_id(clean_graph, database, "higher"),
        },
        database_=database,
    )

    results = retrieve(
        clean_graph, database, query="cybersecurity strategy", embedder=NullEmbedder()
    )

    assert ours.chunk_id not in _by_id(results)


# --- fusion -------------------------------------------------------------------


@pytest.mark.integration
def test_a_chunk_found_by_two_legs_appears_once_carrying_both(clean_graph, database):
    """Fusion, not concatenation. A duplicate row would also rank the chunk twice."""
    embedder = local_or_skip()
    chunk = _seed(
        clean_graph, database, version_id="v", doc_name="ORG 1.0",
        text="Components must document the cybersecurity strategy.",
    )
    embed_chunks(clean_graph, database, version_id="v", embedder=embedder)

    results = retrieve(
        clean_graph, database, query="cybersecurity strategy", embedder=embedder
    )

    matching = [r for r in results if r.chunk_id == chunk.chunk_id]
    assert len(matching) == 1
    assert set(matching[0].signals) >= {"fulltext", "vector"}


@pytest.mark.integration
def test_the_limit_is_respected(clean_graph, database):
    for i in range(5):
        _seed(
            clean_graph, database, version_id=f"v{i}", doc_name=f"DOC {i}",
            text="Components must document the cybersecurity strategy.",
        )

    results = retrieve(
        clean_graph, database, query="cybersecurity", embedder=NullEmbedder(), limit=2
    )

    assert len(results) == 2
