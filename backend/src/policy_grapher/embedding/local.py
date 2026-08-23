"""A sentence-transformers model, running locally.

Local rather than hosted for two reasons. Test runs must work offline, and the
material this corpus is heading toward — controlled unclassified information —
cannot be sent to a third-party API at all. Discovering that after the corpus is
embedded means re-embedding it, so the choice is made now (ADR-016).

`sentence_transformers` is imported inside the constructor, not at module scope.
It pulls in torch and costs about nine seconds to import; paying that on every
`import policy_grapher` would slow the API's startup, the test suite, and every
CLI invocation, for a dependency the default configuration never touches.

Since STORY-052 the library is not installed by default either: it ships in the
optional `local-embeddings` extra, because carrying torch took the backend image
from 399MB to 16.6GB. That makes "configured but absent" a state a real deployment
can be in, so it gets a named exception and a message that says what to install —
raised from `require_sentence_transformers` at startup rather than surfacing as a
ModuleNotFoundError inside `encode` on the first rebuild.
"""

from importlib.util import find_spec


class MissingEmbeddingDependency(RuntimeError):
    """EMBEDDER_ADAPTER is `local`, but the library behind it is not installed."""


MISSING_LIBRARY = (
    "EMBEDDER_ADAPTER is 'local', but sentence-transformers is not installed. "
    "It ships in the optional `local-embeddings` extra, which the default image "
    "leaves out on purpose: it pulls torch and takes the backend image from about "
    "400MB to 16.6GB (STORY-052). Install it with `uv sync --extra local-embeddings`, "
    "or build the image with `--build-arg EXTRAS=\'--extra local-embeddings\'`. "
    "To run without embeddings instead, set EMBEDDER_ADAPTER=null."
)


def require_sentence_transformers() -> None:
    """Fail with something actionable if the optional library is absent.

    `find_spec` rather than an import: it answers the question without paying the
    nine seconds, which is what lets this run at startup on every configuration.
    """
    if find_spec("sentence_transformers") is None:
        raise MissingEmbeddingDependency(MISSING_LIBRARY)


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
            # Repeated from `build_embedder` on purpose: this class is constructed
            # directly in tests and could be elsewhere, and the raw ModuleNotFoundError
            # this replaces named nothing a reader could act on.
            require_sentence_transformers()

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
