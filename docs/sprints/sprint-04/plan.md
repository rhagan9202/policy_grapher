# Sprint 4 — Plan

**Dates:** 2026-08-21 → 2026-08-21 · **Capacity:** One agent-driven working session

*Dated record — written at sprint start, not edited afterward.*

Second sprint in the [tech-debt surge](../../planning/roadmap.md#the-tech-debt-surge).

## Sprint goal

One sentence. If the sprint achieved only this, it was worthwhile.

The application can build an ingested edition's derived layer itself, so Triage, Review and
Ask can be filled without running Python by hand — and a check exists that would catch the
next regression.

## Committed

| ID | Item | Est. | Owner |
| --- | --- | --- | --- |
| [STORY-048](../../backlog/stories/STORY-048-derived-layer-buildable-from-the-app.md) | An ingested edition's derived layer can be built from the running app | L | — |
| STORY-051 | Both suites run on a check nobody has to remember | M | — |
| STORY-052 | The backend image carries only what it needs to run | M | — |
| STORY-056 | A model server is available without installing anything on the host | S | — |

**Total committed:** 1L + 2M + 1S. Four items against sprint 3's seven, because sprint 3's
seven were almost all S and this sprint's L needs a written design before any code — the
[estimation note](../../backlog/README.md#estimation) calls an L carrying an unmade decision
a warning rather than a plan, and STORY-048 has already slipped one sprint for exactly that
reason.

## Why this order

**STORY-048 first, and it starts with a spec rather than a route.** It was deferred from
sprint 3 because its execution model could not be settled in passing: with a real model,
extraction is one call per chunk over 38 chunks, so a synchronous route is wrong the moment
the extractor is not `null`, and the `null` default makes that invisible in every test. Two
proposals were rejected at sprint 3's planning — a deterministic modal-verb extractor as the
demo default, and a synchronous route with the timeout written down as a known limitation —
both on the same ground, recorded in
[ADR-019](../../specs/adr/ADR-019-the-first-run-is-empty.md). Whatever replaces them becomes
the pattern for every future long-running derived-layer operation, so it gets the
architectural treatment: design session, spec, plan, then code.

**STORY-056 before STORY-054, and 056 is the cheap half.** The `local` extraction adapter has
never spoken to a real model, because none exists here — no binary, nothing on :11434. A
containerised Ollama behind a compose **profile** fixes that without installing anything on
the host, which is how Neo4j is already run. The image is 8.43GB and a model several more,
which is precisely why it must not sit on the default path.

**STORY-052 is more urgent than its size suggested.** The backend image measures **16.6GB**.
The estimate that produced the M was 4.9GB, taken from the virtualenv; the image carries build
layers on top. It stays M because the fix is mechanical — an optional dependency group, or a
multi-stage build — but the number is worth writing down before anyone argues it can wait.

**STORY-051 last of the committed items, and it should have been first.** Sprint 3 closed
seven items with nothing but a human remembering to run two commands, and this sprint changes
the most load-bearing code in the project. It is last only because STORY-048 defines what
there is to check.

## Definition of done for this sprint

Beyond the [standing gates](../../backlog/README.md#definition-of-done), carrying forward
sprint 3's addition with the widening its retrospective asked for:

- [ ] **A walkthrough covering each state the data can be in** — empty, documents-only,
      documents with editions, and (new this sprint) a derived layer built through the
      product. Sprint 3's walkthrough found a defect ninety unit tests missed because no test
      had a corpus without editions; the same class of gap is likelier here, not less.
- [ ] **STORY-048's acceptance criterion is met literally**: from a wiped volume, a documented
      sequence of product actions — no Python, no direct Bolt — reaches a Triage row and a
      Review proposal.

## Stretch

Picked up only if committed work finishes early:

- STORY-054 (M) — run the extraction ratchet against a real model and replace the three
  estimated floors with measured ones. Blocked until STORY-056 lands, and then gated on how
  long a multi-gigabyte model pull takes. The gate has never actually gated anything; that it
  skips loudly is the only reason this is stretch rather than committed.

## Known risks

- **STORY-048's design session may consume the sprint, and that is an acceptable outcome.**
  If the execution model needs a spec and a plan and there is no session left to implement it,
  the honest result is "ADR and spec written, route deferred" — recorded as such rather than
  rushed into a route nobody designed. This is the second sprint carrying that risk.
- **A containerised model server makes the stack heavier while STORY-052 is trying to make it
  lighter.** 8.43GB for Ollama plus a model, against a backend image already at 16.6GB. The
  profile keeps it off the default path, but "the stack comes up on one command" is a vision
  constraint and this sprint pushes both ways on it.
- **Trimming the backend image can break the embedding port silently.** `LocalEmbedder`
  imports `sentence_transformers` lazily, so removing the dependency from the default image
  will not fail at startup, at import, or in any test that uses the `null` default — it fails
  the first time someone configures `local`. Whatever STORY-052 does needs a test that proves
  the configured-but-absent case reports something a human can act on.
- **CI has no prior art here and the integration suite needs Docker.** 512 backend tests
  include testcontainers-backed ones that start real Neo4j, and the frontend gate is three
  commands chained. A CI that quietly skips the integration half would be worse than none,
  because it would report green over the tests that actually exercise the database.
- **`source_uri` is a container path.** `rebuild_derived` re-reads the PDF from
  `file:///data/samples/...`, which resolves inside the backend container and nowhere else.
  Fine while the caller is the backend; a trap for anything that moves.
