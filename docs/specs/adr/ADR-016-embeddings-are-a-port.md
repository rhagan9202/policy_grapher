# ADR-016: Embeddings are a port, and the index remembers whose vectors it holds

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

Retrieval needs a semantic leg. The full-text index over chunk text landed in
[ADR-012](ADR-012-chunks-follow-sections.md) and is good at exactly what it is good at — an
exact designator like `DoDI 5000.88` or a section reference like `s.14(2)` is a lexical object,
and a keyword index finds it. It is useless for a question phrased in words the document does
not use, which is how people actually ask.

That means embedding the corpus, and embedding introduces a dependency of a shape this codebase
has met once before. [ADR-013](ADR-013-extraction-is-a-port-with-a-ratchet.md) faced it for the
extraction model and answered with a port: a protocol, a null default that needs no
infrastructure, and an adapter behind it. The same answer applies here for the same reasons, so
most of this ADR is not about the port.

It is about one specific failure. If the configured embedder changes — a different model, a new
revision of the same model, a hosted provider swapped for a local one — and the corpus is not
re-embedded, nothing breaks. Cosine similarity will compare a query vector from model B against
stored vectors from model A perfectly happily and return a number. Results keep arriving, ranked,
plausible-looking, and wrong. There is no exception, no log line, and no degradation a person
would notice from the outside. For a similarity score, "quietly wrong" persists until somebody
independently re-derives the right answer and notices the difference, which in practice is never.

## Options considered

**A hosted embedding API.** Best quality per unit of effort, no local model to manage, no
multi-gigabyte dependency. Rejected on two grounds. Test runs would need network and a key, so
`uv run pytest` stops working on a fresh clone and in CI — the same argument that made the null
extractor the default. And the material this corpus is heading toward is controlled unclassified
information, which cannot be sent to a third-party API at all. That second point is decisive and
it is decisive *now* rather than later: discovering it after the corpus is embedded means
re-embedding the corpus.

**A local model, with no recorded identity.** Embed chunks, store vectors, move on. Rejected: it
is precisely the configuration in which the silent-mismatch failure above is invisible. Nothing
in the graph would be able to answer "whose vectors are these?".

**A local model behind a port, with the index recording its own provenance.** Chosen.

## Decision

**The embedder is a port with a null default.** `embedding.Embedder` is a protocol —
`model_id`, `dimensions`, `embed(texts)`. `NullEmbedder` is the default, so a fresh clone and CI
pass with no model downloaded. `LocalEmbedder` runs a sentence-transformers model on this
machine. `build_embedder(settings)` raises on an unknown name, and `lifespan` calls it, so a
typo in `EMBEDDER_ADAPTER` fails at boot rather than surfacing later as a search that finds
nothing.

**The null embedder returns no vectors, not zero vectors.** `dimensions` is 0 and `embed`
returns an empty list. A zero vector is a real point in the space; under cosine similarity it
would be returned as a plausible neighbour for anything, which is a worse failure than producing
nothing at all. Having no geometry to declare is also why the null embedder creates no index —
there is nothing to configure one with.

**Local, not hosted.** Offline test runs, and the CUI path. Slower and slightly weaker today,
and the only choice that still works when tier-4 material arrives.

**The index records `model_id` and `dimensions`, and a mismatched write is refused.** An
`:EmbeddingIndex` node carries the identity of whichever embedder built the vector index, and
every embedded chunk carries `embedding_model` as well. `ensure_vector_index` compares the
configured embedder against what is recorded and raises `EmbeddingModelMismatch` on either a
different name or a different width — **before** writing anything. The message names *both*
models, because the person reading it needs to know which of the two is the one they did not
mean to configure. This is the whole reason the ADR exists: it converts the phase's most
dangerous failure from silent and permanent into loud and immediate.

**The vector index is created at embed time, not in `apply_schema`.** Its dimensions are a
property of whichever model is configured, so it cannot be one of the fixed statements in
`db.py` that every deployment runs identically. Neo4j does not accept query parameters in index
DDL, so the name and width are interpolated into the statement — both come from configuration
this process resolved and an `int()` conversion, never from a request.

**Embedding is idempotent, and blank chunks are skipped.** A chunk already carrying a vector
from the same model is passed over, so re-running returns 0 rather than rewriting the corpus.
A chunk whose text is empty or whitespace is skipped, because an empty string embeds to a real
point that means nothing and would sit in the index as a plausible neighbour for anything.

**Changing embedder means re-embedding the corpus.** There is no migration and there should not
be one: vectors are not translatable between models. The refusal above is what makes that a
decision someone takes deliberately instead of a state they drift into.

## Consequences

**Makes easy.** Retrieval can add a semantic leg without the rest of the codebase learning that
embeddings exist. Comparing two embedders is a settings change plus a re-embed, and the graph
will not let the comparison be corrupted by leftovers from the first. A future hosted adapter —
if the CUI constraint ever lifts for some corpus — is one file implementing one protocol.

**Makes hard.** `sentence-transformers` pulls `torch`, `transformers` and `scikit-learn`: the
backend virtualenv is about 4.9 GB, and importing the library costs roughly nine seconds. That
is why `LocalEmbedder` imports it inside the constructor and loads the model lazily on first use,
so the default configuration — which never touches it — pays neither cost at startup. It remains
a real weight on the container image, and if that becomes the binding constraint, a lighter
static-embedding library behind the same port is the change to make; the port is what keeps that
change small.

**Commits us to.** Every vector in this graph being attributable to a named model, permanently.
The moment a code path writes an embedding without going through `embed_chunks` — a bulk import,
a migration, a one-off script — the guarantee is gone, and it is gone in the specific way that
produces no error and no symptom. It also commits the project to treating "the corpus is
embedded" as a statement about a *particular* model rather than a boolean, which is the framing
every later retrieval feature has to inherit.
