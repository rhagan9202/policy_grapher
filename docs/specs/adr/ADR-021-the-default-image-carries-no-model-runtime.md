# ADR-021: The default image carries no model runtime

**Status:** Accepted · **Date:** 2026-08-21 · **Deciders:** —

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

[ADR-016](ADR-016-embeddings-are-a-port.md) put embedding behind a port with a `null` default,
so that a fresh clone and its tests need no model. It recorded the cost honestly under *Makes
hard*: `sentence-transformers` pulls `torch`, `transformers` and `scikit-learn`, and the
backend virtualenv measures about 4.9GB. `LocalEmbedder` imports the library inside its
constructor, so the default configuration pays neither the nine-second import nor the memory.

What that mitigation does not touch is the image. Measured at the start of sprint 4:

| Image | Size |
| --- | --- |
| `policy_grapher-backend` | **16.6GB** |
| `policy_grapher-worker` | **16.6GB** |
| `story-037-backend` (the last build before ADR-016) | **378MB** |

Two services, because [STORY-048](../../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md)
runs the worker from the same image. The 4.9GB estimate in the backlog row was taken from the
virtualenv; the image carries build layers on top of it, and the layer is copied twice because
the Dockerfile syncs once without the project and once with it.

The [vision](../../planning/vision.md) constrains this project to a stack that comes up on one
command. A 16.6GB pull for a library that the default configuration never loads is the clearest
violation of that constraint in the repository, and it arrived as a side effect rather than a
decision.

## Decision

**`sentence-transformers` moves out of the default dependencies into an optional
`local-embeddings` extra, and the image installs no extras unless asked.**

1. `pyproject.toml` declares `[project.optional-dependencies].local-embeddings`. The `dev`
   group depends on `policy-grapher[local-embeddings]` rather than restating the version
   floor, so a developer's suite still exercises the real model and the floor has one home.
2. `backend/Dockerfile` takes an `EXTRAS` build argument, empty by default and passed to both
   `uv sync` invocations. `docker-compose.yml` supplies it to `backend` and `worker` alike
   from `BACKEND_EXTRAS`, because both run the same image and the rebuild that embeds runs in
   the worker.
3. **Configuring `local` without the library fails at startup, not at first use.**
   `require_sentence_transformers()` checks with `importlib.util.find_spec` — which answers
   without paying the nine-second import — and raises `MissingEmbeddingDependency` naming the
   extra, the build argument, and the `EMBEDDER_ADAPTER=null` alternative. `build_embedder`
   calls it, and `build_embedder` is what `lifespan` calls.

## Consequences

**Makes easy.** `docker compose up` pulls 399MB per backend service instead of 16.6GB — a
**97.6% reduction**, and back within a rounding error of the 378MB the image measured before
ADR-016. Rebuild times fall with it. The port that ADR-016 built for swapping providers turns
out to be the thing that makes this cheap: nothing outside `embedding/local.py` changed.

**Makes hard.** Turning on a local embedder is now two steps rather than one — set
`EMBEDDER_ADAPTER=local` *and* rebuild with `BACKEND_EXTRAS="--extra local-embeddings"`. That
is a real cost, paid deliberately, and it is why step 3 above exists: the failure it creates is
the one the sprint-4 plan named as this change's central risk, since the lazy import means the
naive version of this decision fails with a `ModuleNotFoundError` raised inside `encode`, on a
queued rebuild, hours after a container started clean and reported itself healthy.

**Assumption:** the extra is the right unit, not a lighter static-embedding library behind the
same port. That option was considered and deferred rather than rejected — it changes what the
vectors mean and therefore what retrieval returns, which is a decision about quality and not
about packaging, and it deserves its own ADR if anyone takes it up.

## Alternatives considered

**A multi-stage build.** Rejected on measurement. It would drop uv's cache and the duplicated
sync layer — roughly 16.6GB to 5GB — while leaving torch in the runtime stage. Five gigabytes
is still an order of magnitude past the 378MB baseline, so the build shape was never the
problem; the dependency was. Worth revisiting only if the image grows again for some other
reason.

**Leaving it and documenting the size.** Rejected for the same reason sprint 3 rejected writing
a synchronous route's timeout down as a known limitation ([ADR-019](ADR-019-the-first-run-is-empty.md)):
a constraint the project has stated in its vision is not satisfied by a note explaining why it
is unmet.
