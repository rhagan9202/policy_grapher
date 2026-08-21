# STORY-048: An ingested edition's derived layer can be built from the running app

**Epic:** — · **Status:** Ready · **Estimate:** L · **Sprint:** 3

## User story

As an analyst evaluating this tool, I want the screens it ships with to have data in them
without my writing Python, so that the product can be demonstrated rather than described.

## Context

DI-2 phases 3 to 6 built extraction, linking, diffing, embedding and retrieval, each with
tests and an ADR. An AST sweep of `src/` on 2026-08-21 found that four of the pieces have
**no caller anywhere in the application**:

| Symbol | Defined in | Called from `src/`? | Covered by tests? |
| --- | --- | --- | --- |
| `rebuild_derived` | `links/rebuild.py` | no | yes |
| `embed_chunks` | `embedding/__init__.py` | no | yes |
| `CachedExtractor` | `extraction/cache.py` | no | yes |
| `GraphCacheStore` | `extraction/cache.py` | no | yes |

`build_extractor` and `build_embedder` *are* called, in `lifespan` — but only to validate the
configured name. Both instances are put on `app.state` and never read. `propose_links` is
called only by `rebuild_derived`, which nothing calls.

The consequences are not subtle:

- **No obligation can ever exist.** Review's queue and Triage's rows both depend on them, so
  both screens are empty by construction.
- **No embedding can ever exist**, so the vector leg of hybrid retrieval never fires and
  `/ask` is permanently a two-signal system, with the semantic half inert.
- **The extraction cache is dead code.** [ADR-013](../../specs/adr/ADR-013-extraction-is-a-port-with-a-ratchet.md)
  spends a substantial section on its key design, and nothing in the product uses it.

This was found because auditing the UI required seeding the graph by hand — running
`write_obligations`, `propose_links` and `diff_versions` from a script against the container's
Neo4j. That is the only way the Triage screenshot in that audit could be produced.

**The tests are green and the product does not work.** Every unit here is correct in
isolation; nothing composes them. That is the specific kind of gap a suite cannot see, and
it is why this story is the surge's first item.

## Acceptance criteria

- [ ] From a clean `docker compose up -d --build` with a wiped volume, a documented sequence
      of **product** actions — no Python, no direct Bolt access — reaches a state where
      Triage shows at least one ranked row and Review shows at least one proposal
- [ ] Extraction runs through `CachedExtractor` backed by `GraphCacheStore`, so a second run
      over an unchanged edition calls the model zero times
- [ ] Embedding runs through `embed_chunks`, and `/ask` returns a hit whose `signals` include
      `vector` for a paraphrased question
- [ ] The route requires a principal and is covered by the `test_auth.py` route enumeration
      without needing a new entry in `OPEN_ROUTES`
- [ ] Running it twice over the same edition is idempotent — same obligation ids, same chunk
      ids, no duplicate proposals
- [ ] `rebuild_derived`'s `MissingSourceError` path is reachable and returns a 4xx that names
      the edition, rather than a 500
- [ ] The default `null` extractor and embedder remain the defaults, so `uv run pytest` and a
      fresh clone still need no model

## Notes

`rebuild_derived` already does almost exactly what is needed — drop, re-chunk, re-extract,
write, propose, replay, all with extraction outside the write transaction. The missing piece
is a caller. The smallest honest change is a route that invokes it for one `version_id`.

Two constraints on that route worth settling before writing it:

**It is long-running.** With a real model, extraction is one call per chunk — the sample
DoDD 5000.01 edition has 38 chunks. A synchronous request will exceed any sensible timeout as
soon as the extractor is not `null`. The default adapter makes this invisible in testing,
which is precisely how it would ship broken.

**`source_uri` is a container path.** `rebuild_derived` re-reads the PDF from the version's
`source_uri`, which ingest wrote as `file:///data/samples/...` — the path *inside* the backend
container. That resolves for the backend and for nothing else, which is fine while the route
lives in the backend and worth knowing before anything moves.

## Open questions

- **Synchronous route, background task, or CLI?** A background task needs status reporting the
  app has no pattern for; a CLI is honest but is not "from the app" and leaves the screens
  undemonstrable to anyone without a shell. A synchronous route is the smallest thing that
  could work and is wrong the moment a real model is configured.
- **Who triggers it — ingest, or a separate action?** Building the derived layer inside
  `POST /ingest` makes a cold start work with no new concept, but couples a fast structural
  operation to a slow model one, and [ADR-012](../../specs/adr/ADR-012-chunks-follow-sections.md)
  was careful to keep ingest atomic.
- **Does this need its own ADR?** Probably yes: whatever is chosen becomes the pattern for
  every future long-running derived-layer operation, and the reasoning will not be obvious
  a year from now.
- **What does it do about `POST /reset`?** Reset clears nodes but cannot drop the Neo4j
  vector index; `ensure_vector_index` rebuilds it only when nothing is embedded. Re-running
  this after a reset should be exercised, not assumed.
