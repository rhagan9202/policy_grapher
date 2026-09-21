"""What stands between a source file's bytes and the chunks stored from it.

An edition carries a stamp of this path alongside the checksum of its source.
Together they answer the question an unchanged re-ingest has to ask before it
discards anything: would running again produce the chunks that are already
there? The checksum alone cannot answer it — it covers the bytes going in, not
the machinery that turns them into chunks ([ADR-042](../../../docs/specs/adr/
ADR-042-an-ingest-that-would-rewrite-nothing-rewrites-nothing.md)).

The stamp is derived, never declared. A hand-maintained version has a silent
failure mode: whoever changes the chunker has to remember to bump it, and the
one time they forget, an edition keeps obligations anchored to text the pipeline
no longer produces — which is the loss ADR-039 refused re-anchoring to avoid,
reached by a different route. Deriving it means a change invalidates it whether
or not anyone noticed making one.

That matters most for the stage nobody edits. Chunk content depends on the PDF
text extraction feeding the chunker, and that dependency is floored with no
upper bound (`pypdf>=6.0`), so an upgrade changes the text this pipeline reads
without a single line changing in this repository. A stamp naming only the
chunker would let exactly that upgrade pass as unchanged.
"""

import hashlib
from pathlib import Path
from types import ModuleType

import pypdf

from policy_grapher import chunking, chunks
from policy_grapher.sources import pdf

# Every stage that can change a chunk's content without the source file
# changing: the extraction that reads the bytes, the chunker that divides them,
# and the writer that decides what is stored of each chunk.
_STAGES: tuple[ModuleType, ...] = (pdf, chunking, chunks)

STAMP_LENGTH = 16


def _stage_digest(module: ModuleType) -> str:
    """One stage's contribution, taken from the source actually imported."""
    path = getattr(module, "__file__", None)
    if path is None:  # pragma: no cover - source is present in every supported install
        # An unknown must behave as the old behaviour does, and the old
        # behaviour is to rewrite. A digest that cannot be computed is reported
        # as a value that matches nothing rather than as a constant, which would
        # match any edition stamped while it was equally unreadable.
        return f"unreadable:{module.__name__}:{hashlib.sha256(id(module).to_bytes(8)).hexdigest()}"
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pipeline_stamp() -> str:
    """A stable identifier for the installed bytes-to-chunks path.

    Equal across two runs exactly when every stage is byte-identical and the
    extraction dependency is the same release. Truncated because it is compared,
    never inverted, and a full digest on every edition is noise in the store.

    Recomputed per call rather than cached. Caching it looks free — the answer
    cannot change under a running process — and a memoised version was written
    and then removed, because the property that makes it safe in production is
    exactly the one the tests have to break: they edit a stage's source, or move
    the dependency's version, to prove the stamp notices. With a cache in place
    one such test left a stamp computed under its own monkeypatch behind, and a
    later test that should have failed passed instead, having compared against
    that stale value rather than the pipeline it was actually running. The saving
    was three file digests on a path that already extracts a PDF and makes a
    dozen round trips; the cost was a guard that stopped guarding.
    """
    parts = [f"pypdf=={pypdf.__version__}"]
    parts.extend(f"{module.__name__}={_stage_digest(module)}" for module in _STAGES)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:STAMP_LENGTH]
