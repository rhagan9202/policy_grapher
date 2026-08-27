"""The MVP definition of done, asserted rather than attested — STORY-094.

`docs/planning/vision.md#what-success-looks-like` lists the bars this product is
judged against, in prose, and until this file nothing verified any of them. A bar
was met according to whoever last read the list.

That is not hypothetical. **The corpus bar stopped being met and nothing
noticed.** Sprints 6 and 7 rebuilt the graph around two editions of one directive,
and at sprint 8's planning it held 2 corpus documents against a bar of 20 — while
50 `:Document` nodes existed, 48 of them `:External` references, so a naive count
would have reported the bar met. Every number those two sprints published was
measured against a single document, and that went unsaid because nothing was
counting.

Each test below names the bar it is about, so a red build says which part of the
definition of done stopped being true.
"""

from pathlib import Path

import pytest

from policy_grapher.ingest import ingest_file
from policy_grapher.sources import DOCUMENT_SUFFIXES
from policy_grapher.sources.manifest import READERS

VISION = Path(__file__).resolve().parents[2] / "docs" / "planning" / "vision.md"
SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
MANIFEST = "dod_policy_references_08122026.csv"

# The bar as the vision states it.
CORPUS_BAR = 20

# What the vision's file-type bar names, and the one that cannot be met.
# DOCX is not absent by oversight: no `.docx` exists in this repository to design
# extraction against, and rules fitted to a document we invented would be measured
# by a ratchet that could not tell us they were wrong. STORY-093 records that at
# the bar itself. Listing it here rather than quietly omitting it is the whole
# point — a definition of done that hides its own gap is worse than one nobody
# checks.
REQUIRED_FORMATS = {".pdf", ".csv", ".xlsx"}
KNOWN_UNMET_FORMATS = {".docx"}

# Bars no test can settle, with the reason. Recorded here so that "checked" has a
# boundary and the boundary is visible.
NOT_CHECKED_HERE = {
    "runs under `docker compose up` from a clean checkout": (
        "a human step; ADR-022 says why CI cannot cover it, and the compose job "
        "builds the images without bringing the stack up"
    ),
    "API calls return successful queries with correct payloads": (
        "the suites are that check; restating it here would be an assertion that "
        "cannot fail"
    ),
}


def test_the_vision_still_states_the_bars_this_file_checks():
    """The guard on the guard. If the vision is reworded, these assertions can
    quietly start checking something nobody claims any more — which is how a gate
    stops gating without failing."""
    text = VISION.read_text(encoding="utf-8")

    assert "Handles a corpus of 20 documents" in text
    assert "Processes PDF, DOCX, XLSX, and CSV file types" in text
    assert "configurable render cap" in text


def test_the_file_type_bar_lists_what_ingestion_accepts():
    """Bar: "Processes PDF, DOCX, XLSX, and CSV file types"."""
    accepted = DOCUMENT_SUFFIXES | set(READERS)

    missing = REQUIRED_FORMATS - accepted
    assert not missing, (
        f"the vision's file-type bar names {sorted(missing)}, which ingestion does "
        f"not accept. Accepted: {sorted(accepted)}."
    )
    assert KNOWN_UNMET_FORMATS.isdisjoint(accepted), (
        f"{sorted(KNOWN_UNMET_FORMATS)} is recorded as an unmet bar and ingestion "
        f"now accepts it — the vision and STORY-093 need updating, and this list "
        f"with them."
    )


@pytest.mark.integration
def test_the_render_cap_bar_is_configurable_and_the_route_honours_it(
    client_with_auth,
):
    """Bar: "Visualizes and explores a graph up to a **configurable render cap,
    defaulting to 300 nodes**".

    The bar is the *configurability*, and asserting `Settings` accepts an override
    would test pydantic rather than this product — a field declared on a model can
    always be overridden. What has to be true is that the route reads the setting,
    which nothing asserted until now: `test_health.py` pins the default and
    `graph.py` is the only place it is used.
    """
    driver = client_with_auth.app.state.driver
    database = client_with_auth.app.state.settings.neo4j_database
    # The cap eats into `:External` nodes only — corpus documents always survive,
    # which `graph.py` says in as many words. A first version of this test seeded
    # two corpus documents, capped at one, and failed: the route was right and the
    # fixture was wrong. Worth recording, because "render cap" does not mean what
    # a reader of the vision alone would assume.
    driver.execute_query(
        "CREATE (:Document {slug: 'ours', name: 'Ours'}), "
        "(:Document:External {slug: 'x', name: 'X'}), "
        "(:Document:External {slug: 'y', name: 'Y'})",
        database_=database,
    )

    original = client_with_auth.app.state.settings
    try:
        client_with_auth.app.state.settings = original.model_copy(
            update={"graph_render_cap": 1}
        )
        # `include_external` defaults to false, and the cap trims externals — so
        # without asking for them there is nothing for the cap to act on, and the
        # test would pass against a route that ignored the setting entirely.
        body = client_with_auth.get("/graph?include_external=true").json()
    finally:
        client_with_auth.app.state.settings = original

    # One corpus document survives; both externals are trimmed by a cap of 1.
    assert body["returned_nodes"] == 1, (
        "the graph route did not honour `graph_render_cap`, so the vision's "
        "configurable-render-cap bar is met by the setting existing and by nothing "
        "reading it"
    )
    assert body["truncated"] is True
    assert body["total_nodes"] == 3


def test_the_bars_no_test_settles_are_named_with_their_reason():
    """"Checked" needs a boundary, and the boundary needs to be visible. A file
    that silently omitted the bars it cannot check would read as complete."""
    assert NOT_CHECKED_HERE
    for bar, reason in NOT_CHECKED_HERE.items():
        assert reason.strip(), f"{bar} is excluded with no reason given"


@pytest.mark.integration
def test_the_corpus_bar_counts_documents_not_nodes(clean_graph, database):
    """Bar: "Handles a corpus of 20 documents".

    Counting `:Document` nodes reports the bar met when it is not: at sprint 8
    planning the graph held 50 of them and 2 documents, the other 48 being
    `:External` references to issuances nobody has ingested. The bar is about the
    corpus, and a reference is not a corpus member.
    """
    ingest_file(clean_graph, database, MANIFEST, SAMPLES)

    records, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) WHERE NOT 'External' IN labels(d) RETURN count(d) AS n",
        database_=database,
    )
    corpus = records[0]["n"]

    all_nodes, _, _ = clean_graph.execute_query(
        "MATCH (d:Document) RETURN count(d) AS n", database_=database
    )

    assert corpus >= CORPUS_BAR, (
        f"the vision's corpus bar is {CORPUS_BAR} documents and the sample "
        f"manifest yields {corpus}. ({all_nodes[0]['n']} `:Document` nodes exist, "
        f"but most are `:External` references and are not corpus members.)"
    )
