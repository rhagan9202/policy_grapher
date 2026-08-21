"""The embedder that produces nothing.

The default, so `uv run pytest` and a fresh clone work with no model downloaded.
`dimensions` is 0 because it has no geometry to declare — which is also why it
creates no index: there is nothing to configure one with.

It returns an empty list rather than zero vectors. A zero vector is a real point
in the space, and under cosine similarity it would be returned as a plausible
neighbour for anything.
"""


class NullEmbedder:
    model_id = "null"
    dimensions = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        return []
