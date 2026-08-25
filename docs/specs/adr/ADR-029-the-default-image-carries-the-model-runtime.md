# ADR-029: The default image carries the model runtime

**Status:** Accepted · **Date:** 2026-08-25 · **Deciders:** Project owner
**Supersedes:** [ADR-021](ADR-021-the-default-image-carries-no-model-runtime.md)

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

ADR-021 moved `sentence-transformers` out of the default dependencies because the default
configuration never loaded it: `EXTRACTOR_ADAPTER` and `EMBEDDER_ADAPTER` both resolved to
`null`, so a 16.6GB pull bought nothing the running stack used. That was the whole argument —
not that the library was unwanted, but that paying for it by default was paying for something
nobody had configured.
[ADR-028](ADR-028-the-default-stack-carries-its-models.md) removes the premise. `ollama` and
`ollama-pull` become ordinary services, and `EXTRACTOR_ADAPTER` and `EMBEDDER_ADAPTER` default
to `local` for both `backend` and `worker`. The default configuration now loads the library
ADR-021 kept out.

## Decision

The default image carries the model runtime. `EXTRAS` defaults to `--extra local-embeddings`,
so `policy_grapher-backend` and `policy_grapher-worker` are about 16.6GB each on the default
path — the same figure ADR-021 measured and removed. The lean path, reached through
`docker-compose.lean.yml`, keeps ADR-021's 399MB, and it is the one image CI still builds and
measures against the 1GB gate.

## Consequences

**Makes hard, stated first because it is what this decision costs.** STORY-052 took these
images from 16.6GB to 399MB — a 97.6% reduction ADR-021 recorded as its central result — and
this decision gives that reduction back for the default path. Every `up --build` on a cold
cache now moves roughly 13GB before anything renders, on top of the 13GB ADR-028 already
charges for the model server itself: two 16.6GB image builds where the lean path builds two
399MB ones. The 1GB CI gate keeps testing true, but only for the lean path; the number it
reports no longer describes the image `docker compose up --build` produces by default.

**Makes easy.** Ask acquires its vector leg. A question phrased in words the document does not
use can reach the passage that answers it, which is the entire argument
[ADR-016](ADR-016-embeddings-are-a-port.md) made for embedding the corpus in the first place —
and it was unreachable by default from the day ADR-021 shipped until now, because the port
existed but nothing set it to `local`.

## Not attempted

ADR-021 recorded a route to roughly 5GB through a multi-stage build that drops `uv`'s cache and
the duplicated sync layer, while leaving `torch` in the runtime stage. It stays unexplored here
too. This decision gives the size back rather than optimising it; the 5GB route is still open
to whoever takes it up, and it would apply to the default path's 16.6GB exactly as it would
have applied to ADR-021's own.

## Supersedes

[ADR-021](ADR-021-the-default-image-carries-no-model-runtime.md). Its measurements — 16.6GB
against 399MB, taken at the start of sprint 4 — and its decision to gate the image at 1GB in CI
both stand as an accurate record of what was true and right on 2026-08-21, and they still
describe the lean path exactly. What no longer holds is the claim underneath the trade: that
the default configuration never loads the library. ADR-028 made that claim false, and this ADR
is the record of what was chosen once it was.
