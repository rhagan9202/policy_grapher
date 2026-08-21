"""A sentence-transformers model, running locally.

Local rather than hosted for two reasons. Test runs must work offline, and the
material this corpus is heading toward — controlled unclassified information —
cannot be sent to a third-party API at all. Discovering that after the corpus is
embedded means re-embedding it, so the choice is made now (ADR-016).

`sentence_transformers` is imported inside the constructor, not at module scope.
It pulls in torch and costs about nine seconds to import; paying that on every
`import policy_grapher` would slow the API's startup, the test suite, and every
CLI invocation, for a dependency the default configuration never touches.
"""


class LocalEmbedder:
    def __init__(self, *, model: str) -> None:
        self._model_name = model
        self._model = None

    @property
    def model_id(self) -> str:
        """Part of the index's recorded identity, so it names the exact model."""
        return f"local:{self._model_name}"

    def _loaded(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dimensions(self) -> int:
        model = self._loaded()
        # Renamed in sentence-transformers 6; the old name still works but warns.
        # Both are supported so the floor in pyproject.toml can stay at >=5.
        if hasattr(model, "get_embedding_dimension"):
            return model.get_embedding_dimension()
        return model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._loaded().encode(texts, convert_to_numpy=True)
        return [[float(value) for value in vector] for vector in vectors]
