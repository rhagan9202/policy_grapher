# Sprint 4 — Review

**Date:** 2026-08-22

*Dated record — a snapshot of what happened.*

## Against the goal

Goal was: the application can build an ingested edition's derived layer itself, so Triage,
Review and Ask can be filled without running Python by hand — and a check exists that would
catch the next regression.

**Met, and only on the sprint's last day.** The check exists: both suites run on every push and
pull request. The application builds a derived layer itself, and — verified end to end against a
real model on 2026-08-22 — that layer reaches a ranked Triage row and a Review queue of 313
proposals. Getting there required fixing two defects the walkthrough found, which is the real
story of this sprint.

Suites at close: **550 backend tests** (512 at sprint start), **90 frontend tests**, both green,
output pristine. Backend and worker images: **399MB**, from 16.6GB.

## Completed

| ID | Item | Est. |
| --- | --- | --- |
| [STORY-048](../../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) | An ingested edition's derived layer can be built from the running app | L |
| STORY-051 | Both suites run on a check nobody has to remember | M |
| STORY-052 | The backend image carries only what it needs to run | M |
| STORY-056 | A model server is available without installing anything on the host | S |
| STORY-054 | The extraction ratchet has been run against a real model at least once | M *(stretch)* |
| STORY-057 | One unparseable item does not destroy the whole rebuild | — *(found and fixed in-sprint)* |
| STORY-058 | The extractor's per-call timeout is configurable | — *(found and fixed in-sprint)* |

**Delivered:** 4 of 4 committed, the stretch, and two defects found by the closing walkthrough
and fixed rather than filed. The first sprint whose commitment was deliberately small — four
items against sprint 3's seven — because one was an L needing a design session, a spec and a
plan before any code. It took roughly the three-items-worth the
[estimation note](../../backlog/README.md#estimation) implies.

**STORY-052 was 3.4× larger than its backlog row said, and still fit its M.** The row estimated
4.9GB from the virtualenv; the images measured **16.6GB**. `sentence-transformers` moved to an
optional `local-embeddings` extra, the Dockerfile took an `EXTRAS` build argument, and compose
passes it to backend and worker alike
([ADR-021](../../specs/adr/ADR-021-the-default-image-carries-no-model-runtime.md)). Nothing
outside `embedding/local.py` and packaging changed —
[ADR-016](../../specs/adr/ADR-016-embeddings-are-a-port.md)'s port earning its keep on a swap it
was not designed for.

**The risk the plan named for STORY-052 was real, and so was one it didn't.** The named one:
`LocalEmbedder` imports lazily, so removing the dependency would first have failed inside
`encode`, during a queued rebuild, on a container that started clean and reported itself healthy.
`require_sentence_transformers()` now checks with `find_spec` from `build_embedder`, which is
what `lifespan` calls, so a misconfigured container refuses to start and names the extra, the
build flag and the `null` alternative. The unnamed one: `uv run` syncs the default dependency
groups before running anything, `dev` is one of them, and `dev` pulls the extra — so the 399MB
image started containers that downloaded torch. `UV_NO_SYNC=1` fixes it and `tests/test_image.py`
guards the line. That also repaired a pre-existing untruth: `architecture.md` claimed ruff never
enters the backend image, and until this sprint every container reinstalled it at startup.

**STORY-051's integration step is structural, not documentary.** `pytest` exits 5 when a marker
selects nothing — verified against this repository before being relied on — so the step selecting
`-m integration` fails if the marker is renamed or the tests disappear. A single combined run
would have gone green over the same event.
[ADR-022](../../specs/adr/ADR-022-both-suites-run-on-every-push.md) records the shape, including
the compose-build job deliberately left out.

## The walkthrough

Sprint 4's Definition of Done, run against a wiped volume. **It found three defects, none of
which 543 tests could see, and all three were fixed before this sprint closed.**

| State | Result |
| --- | --- |
| Empty | 0 documents, 0 graph nodes, review queue empty, frontend 200 |
| Documents only | 438 documents, **0 with editions** — the shape that broke Triage in sprint 3 |
| Documents with editions | 2 editions of DoDD 5000.01, `supersedes` chain correct |
| Derived layer built through the product | **38 and 34 chunks, 120 and 121 obligations, 313 proposals** |
| Triage and Review filled | **1 ranked Triage row**, 313-item Review queue |

**1. Every container was running the model ADR-020 forbids.** `docker-compose.yml` passed
`EXTRACTOR_MODEL: ${EXTRACTOR_MODEL:-qwen3:8b}` to backend and worker, against `config.py`'s
`llama3.1:8b` and against `ollama-pull`, which pulls llama. So a machine whose `.env` predated
the key — this one — asked Ollama for a model that was never pulled and that
[ADR-020](../../specs/adr/ADR-020-model-weights-come-from-us-organisations.md) excludes on
provenance grounds. ADR-020 states it is "enforced by a test, not by a convention"; that test
asserts on `Settings(_env_file=None)`, which resolves a developer's shell, where
`EXTRACTOR_MODEL` is unset. **It passed everywhere it ran while the deployed configuration
violated it everywhere it ran.** Fixed, with a test that reads `docker-compose.yml` and asserts
the defaults are US-origin *and* agree with the application default.

**2. One unparseable item destroyed the whole rebuild.** The model returned `modality: null`;
validation rejected it — correctly, the enum is closed on purpose — and the run failed at **chunk
5 of 38**, discarding four chunks of finished work. Loud failure on a bad *item* is the design;
ending the *run* was never a decision, just what falls out of a bare loop. `rebuild_derived` now
catches it per chunk, counts `chunks_rejected`, and raises `ExtractionFailed` only if *every*
chunk was rejected — so tolerance cannot turn a broken model into a green run
([ADR-023](../../specs/adr/ADR-023-a-rejected-item-costs-its-chunk-not-the-run.md)). The closing
run rejected exactly one chunk of 34 and completed.

**3. The per-call HTTP timeout was a hardcoded 120s.** The second rebuild died on chunk 1 of 34
with `httpx.ReadTimeout` on a host measured at ~7 tokens/second. `rebuild_job_timeout_seconds`
*is* configurable at 1800, with a comment explaining that a real-model rebuild admits no short
timeout that is not a false alarm — reasoning applied to the job and not to the HTTP call inside
it. Now `EXTRACTOR_TIMEOUT_SECONDS`, defaulted to 600.

**STORY-048's acceptance criterion is met literally.** From a wiped volume, a sequence of product
actions — no Python, no direct Bolt — reaches a ranked Triage row and a Review proposal. The
sequence is written down in the [README](../../../README.md#filling-triage-and-review) so it is
repeatable rather than a claim. One detail worth keeping: Triage reported 234 changes and **zero
rows** until a proposal was approved, because a change stays unlinked until something of yours
implements the clause it touches. That is correct behaviour and it reads as a bug until you know.

## Not completed

Nothing. No item was dropped, deferred, or carried.

## Demo notes and feedback

**The stack is dramatically cheaper to run and no more impressive to look at.** 16.6GB to 399MB
per backend service is the sprint's most visible number and changes nothing a user sees. That is
the shape of a tech-debt surge, and the second sprint running where the honest demo is "the same
screens, fewer ways to be wrong".

**Turning on a local embedder is now two steps instead of one** — `EMBEDDER_ADAPTER=local` plus a
rebuild with `BACKEND_EXTRAS="--extra local-embeddings"`. Paid deliberately, and the reason the
misconfiguration refuses at startup rather than mid-rebuild.

**The extraction path had never been walked end to end until this sprint's last day.** STORY-054
ran the ratchet against curated fixtures and passed. The first real corpus PDF failed twice, for
two different reasons, in under twenty minutes. Every walkthrough before this one satisfied its
"derived layer" bullet with `EXTRACTOR_ADAPTER=null`, which writes chunks and no obligations — so
the half of the pipeline that needs a model was green by never being run. That is the finding to
carry into sprint 5 planning.

**A first look at what extraction actually produces.** 120 obligations from the 2018 edition and
121 from the 2020 one, against 234 detected changes and 313 proposals — and
[STORY-055](../../backlog/backlog.md#ready) says `will` outnumbers `shall` 458 to 93 across the
samples, so this is a minority of the duties in the corpus. The numbers are a floor, not a
measure.
