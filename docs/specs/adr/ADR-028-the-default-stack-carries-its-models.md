# ADR-028: The default stack carries its models

**Status:** Accepted · **Date:** 2026-08-25 · **Deciders:** Project owner

*Dated record — written once, not edited afterward. Supersede rather than revise.*

## Context

`docker compose up --build` today brings up five services and no model server.
`EXTRACTOR_ADAPTER` defaults to `null`, so a rebuild writes chunks and zero obligations, and
Review and Triage cannot fill no matter what the reader does — the product explains this in the
README rather than showing it on the screen. Ask fares no better: with `EMBEDDER_ADAPTER` also
`null`, the semantic leg [ADR-016](ADR-016-embeddings-are-a-port.md) built has never been
reachable from a plain `up`, only its lexical one.

`ollama` and `ollama-pull` have carried `profiles: ["models"]` since the model server was
added. A Compose profile is only active when named, so neither service starts on `docker
compose up`, and — the asymmetry that prompted this ADR — neither stops on `docker compose
down` either. A service the default command never starts is a service the default command also
cannot stop; a reader who ran `--profile models up` once is left running it forever, by hand,
until they remember `docker compose --profile models down`.

## Decision

The default stack is the whole product. `ollama` and `ollama-pull` lose their `profiles` key
and become ordinary services, started and stopped like every other one. `EXTRACTOR_ADAPTER` and
`EMBEDDER_ADAPTER` default to `local` for both `backend` and `worker`, and the build argument
the two images share, `EXTRAS`, defaults to `--extra local-embeddings` via `BACKEND_EXTRAS`. An
`.env` that names any of these still wins, so an existing checkout keeps whatever it already
set. A stack with no models is reached through `docker-compose.lean.yml`, applied as a second
`-f` argument — a file a reader opts into, not a variable they have to know to unset.

## Consequences

**Makes easy.** `docker compose down` now stops everything `docker compose up` started,
including the model server, closing the asymmetry that motivated this change. A newcomer
running one documented command reaches a stack where Review, Triage, and Ask's semantic leg can
all fill, rather than discovering from the README that three screens are structurally empty
until they read further and run a second command.

**Makes hard.** The cost is real and front-loaded. A fresh clone now moves roughly 13GB before
the first screen renders — `ollama/ollama` at 8.43GB, `llama3.1:8b` at about 4.9GB — and builds
two 16.6GB images, backend and worker sharing the layer, in a first build measured in tens of
minutes rather than seconds. [ADR-019](ADR-019-the-first-run-is-empty.md)'s empty first run
still holds: `AUTO_INGEST` is unchanged and nothing is ingested by default. It is only expensive
to arrive at the point where ingesting is possible.

## Alternatives considered

**`COMPOSE_PROFILES=models` in `.env`.** Would have delivered the same default in one line and
fixed `down` at the same time. Rejected: `.env` is untracked, and this project has twice been
bitten by an `.env` predating the keys `.env.example` documents — most recently in the README
addendum of 2026-08-24. Which services exist by default belongs in the file every clone
actually gets, not in one a fresh clone might not have, or might have wrong.

**`--scale ollama=0 --scale ollama-pull=0` for the lean path.** Genuinely removes the
containers. Rejected as the lean mechanism because it cannot return `EXTRACTOR_ADAPTER` and
`EMBEDDER_ADAPTER` to `null` — it produces a stack that looks healthy, reports itself running,
and fails on every rebuild against a model server that was scaled away. The adapters have to
turn off in the same place the services do, which a flag on the command line cannot do and a
file can.
