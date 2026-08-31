"""Canary replay: what a prompt change moved, over real chunks, without labels.

The gold set asks whether an answer is right and needs eight hand-labelled
fixtures to do it. This asks a cheaper question that scales: did anything
change? Three sprints running, a prompt edit degraded an unrelated passage and
was caught only because the passage happened to be a fixture.

Deliberately not a pass/fail gate. A diff is information, not a regression —
most prompt changes are supposed to move something. What was missing was any
way to see the rest of what moved.
"""

from pathlib import Path

from policy_grapher.chunking import chunk_pages
from policy_grapher.extraction.schema import normalize
from policy_grapher.sources import pdf

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "canary"

# How many chunks the recorded baseline covers. A canary replay exists to be run
# after every PROMPT_VERSION bump, when the extraction cache misses by design —
# so every future replay costs the same again. A size nobody will wait for is
# not a blast-radius check, so this is measured, not guessed: on 2026-08-31,
# llama3.1:8b (this project's shipped model, "schema" decoding) was timed over
# 13 real chunks pulled from `select_canary_chunks` — 8 from the round-robin's
# first pass (each document's opening chunk; 530.1s, avg 66.3s/chunk) and 5 from
# mid-corpus content sections (134.1s, avg 26.8s/chunk) — for a combined 664.2s
# over 13 chunks, 51.1s/chunk, with per-chunk cost ranging 14.4s-123.7s. A
# 45-minute (2700s) budget divided by that rate extrapolates to ~53 chunks;
# 40 was chosen instead of that ceiling to leave headroom against the observed
# variance (40 chunks lands at ~34 min at the combined average, ~44 min even at
# the slower first-pass average). Tunable: raise it if a future measurement on
# faster hardware shows more room, lower it if the corpus or model changes the
# per-chunk cost.
CANARY_BASELINE_SIZE = 40


def select_canary_chunks(limit: int = 120) -> list[dict]:
    """A deterministic slice of the corpus: every sample PDF, chunks in order,
    round-robin across documents so no single document dominates the set.

    Deterministic because a canary set that varies between runs cannot tell a
    prompt change from a sampling change.

    `chunk_pages` takes a document's page texts and a `version_id` keyword-only
    (verified against `chunking.py`; the brief's draft called it positionally
    with no `version_id`, which raises `TypeError`). `version_id` is hashed into
    `chunk_id` (see `_chunk_id` in chunking.py), so it has to be stable across
    runs for this function's own determinism test to hold — the sample PDF's
    filename stem is used, the same choice `test_extraction_adapters.py` and
    `test_rebuild.py` already make for the same reason. `extract_document`
    returns pages on `.pages` (`ExtractedDocument.pages`, confirmed in
    `sources/document.py`), not the bare list the brief's draft assumed.
    """
    per_document: list[list[dict]] = []
    for path in sorted(SAMPLES.glob("*.pdf")):
        document = pdf.extract_document(path)
        chunks = [
            {
                "chunk_id": chunk.chunk_id,
                "text": chunk.text,
                "section_path": chunk.section_path,
                "section_title": chunk.section_title,
            }
            for chunk in chunk_pages(document.pages, version_id=path.stem)
        ]
        per_document.append(chunks)

    out: list[dict] = []
    for index in range(max((len(c) for c in per_document), default=0)):
        for chunks in per_document:
            if index < len(chunks):
                out.append(chunks[index])
                if len(out) == limit:
                    return out
    return out


def record(extractor, chunks: list[dict]) -> dict:
    """What the extractor says about each chunk, in a form a diff can read.

    Statements are normalised with the same function obligation identity is
    hashed from, so a whitespace change is not reported as a moved duty. A chunk
    the extractor refuses records `None`, which is itself a signal: a chunk that
    starts or stops being rejected is one of the largest things a prompt edit
    can do.
    """
    out: dict[str, list[dict] | None] = {}
    for chunk in chunks:
        try:
            found = extractor.extract(
                chunk["text"],
                section_path=chunk["section_path"],
                section_title=chunk["section_title"],
            )
        except ValueError:
            out[chunk["chunk_id"]] = None
            continue
        out[chunk["chunk_id"]] = sorted(
            (
                {"statement": normalize(o.statement), "modality": str(o.modality)}
                for o in found
            ),
            key=lambda item: item["statement"],
        )
    return out


def diff(baseline: dict, current: dict) -> dict:
    """Per chunk: what the baseline had, what the current run has, where they differ."""
    moved, added, removed = [], [], []
    for chunk_id in sorted(set(baseline) | set(current)):
        was, now = baseline.get(chunk_id, "absent"), current.get(chunk_id, "absent")
        if was == now:
            continue
        if was == "absent":
            added.append(chunk_id)
        elif now == "absent":
            removed.append(chunk_id)
        else:
            moved.append({"chunk_id": chunk_id, "was": was, "now": now})
    return {"moved": moved, "added": added, "removed": removed}
