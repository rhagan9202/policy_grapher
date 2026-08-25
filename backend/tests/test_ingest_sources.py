"""What the Ingest screen can offer, and why it must agree with the ingester.

`POST /ingest` takes a bare filename because the backend reads from its own
container. Nothing told a reader which filenames existed, so the screen was a
free-text box over a directory only the server could see — know the name or
guess. This route is that directory, read out loud.

The load-bearing property is not that the listing exists but that it does not
disagree with `ingest_file`. A picker that labels a file one way while ingest
treats it another is worse than the text box it replaces: it is confidently
wrong rather than merely unhelpful.
"""

from pathlib import Path

import pytest

from policy_grapher.sources import is_document_source

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"


@pytest.mark.integration
def test_the_listing_names_every_file_in_the_data_directory(client_with_auth):
    body = client_with_auth.get("/ingest/sources").json()

    listed = {row["filename"] for row in body}
    on_disk = {path.name for path in SAMPLES.iterdir() if path.is_file()}
    assert listed == on_disk


@pytest.mark.integration
def test_every_listed_kind_agrees_with_the_ingester(client_with_auth):
    """The property this route exists to keep.

    `kind` must be derived from the same predicate `ingest_file` branches on,
    not from a second rule that happens to agree today.
    """
    body = client_with_auth.get("/ingest/sources").json()

    assert body, "the sample directory is not empty, so neither is this"
    for row in body:
        expected = "document" if is_document_source(SAMPLES / row["filename"]) else "manifest"
        assert row["kind"] == expected, f"{row['filename']} listed as {row['kind']}"


@pytest.mark.integration
def test_a_listed_file_carries_its_size(client_with_auth):
    body = client_with_auth.get("/ingest/sources").json()

    row = next(r for r in body if r["filename"] == "500001p_2020.pdf")
    assert row["size_bytes"] == (SAMPLES / "500001p_2020.pdf").stat().st_size


@pytest.mark.integration
def test_nothing_is_ingested_until_something_is(client_with_auth):
    body = client_with_auth.get("/ingest/sources").json()

    assert all(row["ingested"] is False for row in body)


@pytest.mark.integration
def test_a_file_that_has_been_ingested_says_so(client_with_auth):
    """And only that file — the flag is per source, not a global 'something ran'."""
    client_with_auth.post("/ingest", json={"filename": "500001p_2020.pdf"})

    body = client_with_auth.get("/ingest/sources").json()
    ingested = {row["filename"] for row in body if row["ingested"]}

    assert ingested == {"500001p_2020.pdf"}


@pytest.mark.integration
def test_the_listing_is_sorted_by_name(client_with_auth):
    """A directory listing in filesystem order changes between machines."""
    body = client_with_auth.get("/ingest/sources").json()

    names = [row["filename"] for row in body]
    assert names == sorted(names)


@pytest.mark.integration
def test_the_route_requires_a_principal(client_with_graph):
    assert client_with_graph.get("/ingest/sources").status_code == 401
