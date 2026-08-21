"""Test doubles shared between suites.

`FakeEmbedder` exists so the index-provenance guards can be tested for what they
record and refuse, without a real model making those tests slow and no stronger.
`local_or_skip` is for the two things only a real model can demonstrate — that
vectors have the declared width, and that a paraphrase is reachable at all.
"""

import pytest


class FakeEmbedder:
    """A stand-in with a declared identity and no model behind it."""

    def __init__(self, *, model_id: str = "fake-a", dimensions: int = 4) -> None:
        self.model_id = model_id
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [
            [float((hash(text) >> (8 * i)) % 100) / 100.0 for i in range(self.dimensions)]
            for text in texts
        ]


LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def local_or_skip():
    """A real local embedder, or a skip that says plainly what did not run."""
    from policy_grapher.embedding.local import LocalEmbedder

    embedder = LocalEmbedder(model=LOCAL_MODEL)
    try:
        embedder.embed(["warm up"])
    except Exception as exc:  # noqa: BLE001 - any load failure means the same thing
        pytest.skip(
            "THE LOCAL EMBEDDER WAS NOT EXERCISED: the model could not be loaded "
            f"({type(exc).__name__}: {exc}). A green suite does not mean it works."
        )
    return embedder
