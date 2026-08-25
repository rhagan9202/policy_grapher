# Models in the Default Stack — Design

**Date:** 2026-08-25 · **Status:** Approved, ready for an implementation plan

Design for inverting which stack `docker compose up --build` brings up. Today it brings up a
lean stack with no models, and the full product is reached by naming a profile. After this it
brings up the full product, and the lean stack is the flagged path.

## Goal

The stack a newcomer gets on one command should be the product, not a subset of it that leaves
three screens permanently empty. Today `docker compose up --build` produces a system where
Review and Triage cannot fill no matter what the reader does, because the default
`EXTRACTOR_ADAPTER=null` extracts nothing — and the reader has to find that out from the README
rather than from the product.

| Story | Delivers | Size |
| --- | --- | --- |
| STORY-078 | `docker compose up --build` brings up the whole product | M |
| STORY-079 | A lean stack with no models is one documented command | S |
| STORY-080 | CI builds and measures the lean stack, and says which stack it measured | M |

## What is already true

Verified against the running system on 2026-08-25.

- `ollama` and `ollama-pull` both carry `profiles: ["models"]`. Neither starts on a plain `up`,
  and — because a profile is only active when named — `docker compose down` does not stop them
  either. That asymmetry is the reported annoyance.
- `COMPOSE_PROFILES=models docker compose config --services` resolves all seven services;
  `COMPOSE_PROFILES=` resolves five. The mechanism works in both directions.
- `docker compose up --scale <svc>=0` genuinely excludes a service, and an override file setting
  `deploy: replicas: 0` does the same. Both were tested against a two-service probe, and the
  scale form was tested against a `depends_on: service_healthy` relationship.
- Compose resolves `EXTRACTOR_BASE_URL` to `http://ollama:11434` for both backend and worker,
  overriding the `Settings` default of `localhost:11434`. Nothing here changes that.
- Images today: `policy_grapher-backend` and `policy_grapher-worker` at **400MB** each;
  `ollama/ollama` at **8.43GB**; `llama3.1:8b` a further ~4.9GB, already pulled on this machine.
- `.github/workflows/ci.yml` has a step **"The default image has not regrown"** that fails when
  either image exceeds 1GB, quoting ADR-021 in its error.
- `backend/tests/test_ci.py` asserts the compose job builds through compose and covers every
  service that has a `build:` key. Both assertions read the workflow and `docker-compose.yml`.
- Both suites are green: backend 595 passed / 5 skipped, frontend 169 passed.

## Decisions taken

**The full stack means extraction *and* embeddings.** Extraction alone would have left ADR-021
untouched, because ollama is a separate container and the backend image stays 400MB. Including
embeddings compiles `sentence-transformers` into the backend and worker images and takes them to
16.6GB. That is the expensive half and it was chosen deliberately.

**The default stack's shape lives in `docker-compose.yml`, not in `.env`.** Setting
`COMPOSE_PROFILES=models` in `.env` would have delivered the same default in one line, and would
have fixed `down` at the same time. It was rejected: `.env` is untracked, and this project has
twice been bitten by an `.env` that predates the keys `.env.example` documents — most recently
in the README addendum written on 2026-08-24. Putting *which services exist by default* behind
that file repeats the mistake at higher stakes, and a fresh clone should not depend on it.

**Lean is an override file, not `--scale`.** `--scale ollama=0 --scale ollama-pull=0` works, but
it can only remove containers. It cannot return `EXTRACTOR_ADAPTER` to `null`, so it produces a
stack that looks healthy and fails on every rebuild against a model server that is not there. An
override file turns the services off and the adapters back in one place, and cannot be
half-applied the way two flags can.

**CI keeps building and measuring the lean stack.** The size gate exists to prove the lean image
has not silently regrown, and that purpose survives the default changing. Building 16.6GB images
on every push is a cost with no matching benefit — the images CI can meaningfully police are the
ones whose size is a decision, and the full stack's size is now a documented consequence instead.

## The work

### 1. The default stack

**STORY-078.** `ollama` and `ollama-pull` lose their `profiles:` key and become ordinary
services. `docker compose up --build` starts them; `docker compose down` stops them, which is
the reported annoyance and it falls out of the same change rather than needing its own.

The adapters default on, in `docker-compose.yml`, for both `backend` and `worker`:

```yaml
EXTRACTOR_ADAPTER: ${EXTRACTOR_ADAPTER:-local}
EMBEDDER_ADAPTER:  ${EMBEDDER_ADAPTER:-local}
```

and the build argument both images share:

```yaml
EXTRAS: ${BACKEND_EXTRAS:---extra local-embeddings}
```

An `.env` that names any of these still wins, so an existing checkout keeps whatever it set.

The comment block above `ollama` currently instructs the reader to run
`docker compose --profile models up -d`. It becomes the inverse: why the default carries the
model server, and where the lean path is documented.

### 2. The lean stack

**STORY-079.** A tracked `docker-compose.lean.yml`:

```yaml
services:
  ollama:      { deploy: { replicas: 0 } }
  ollama-pull: { deploy: { replicas: 0 } }
  backend:
    build: { args: { EXTRAS: "" } }
    environment: { EXTRACTOR_ADAPTER: "null", EMBEDDER_ADAPTER: "null" }
  worker:
    build: { args: { EXTRAS: "" } }
    environment: { EXTRACTOR_ADAPTER: "null", EMBEDDER_ADAPTER: "null" }
```

Invoked as one command:

```bash
docker compose -f docker-compose.yml -f docker-compose.lean.yml up --build
```

The adapters must be turned back in the same file that turns the services off. A lean stack
still pointing at `EXTRACTOR_ADAPTER=local` is the failure this file exists to prevent.

**The two stacks share image tags, so switching between them rebuilds.** `EXTRAS` is a build
argument, and both invocations produce `policy_grapher-backend`. Running lean after full — or the
reverse — without `--build` leaves the previous stack's image in place, which for the lean
direction means a 16.6GB image quietly serving a stack that claims to carry no model runtime. The
documented commands therefore both carry `--build`, and the plan verifies the lean build actually
produces a sub-1GB image rather than reusing the full one.

### 3. CI

**STORY-080.** The compose job builds with the override file, so it continues to measure the
lean image against its 1GB threshold. Two things must change with it or the job becomes a lie:

- The step name and its error message quote ADR-021. They must name the ADR that supersedes it
  and say plainly that the measured stack is the lean one, not the default one.
- `backend/tests/test_ci.py` asserts the compose job builds through compose and covers every
  service with a `build:` key. Both assertions must be updated to the override-file invocation
  and re-read to confirm they still assert something — a test that passes because it now matches
  a looser string is the failure mode this project has hit three times.

### 4. The record

**ADR-028 — the default stack carries its models.** Why one command now brings up the product
rather than a subset, what it costs a fresh clone (~13GB of pulls, 16.6GB images, a first build
measured in tens of minutes), and that ADR-019's empty first run still holds: nothing is
ingested, it is only expensive to get there.

**ADR-029 — superseding ADR-021.** ADR-021 is Accepted and frozen; it is not edited. ADR-029
records that its trade — 399MB against a library the default configuration never loads — stops
holding the moment the default does load it, and that STORY-052's 16.6GB → 399MB reduction is
deliberately given back for the default path while the lean path keeps it. It must state what is
lost, not only what is gained: every `up --build` on a fresh machine now moves ~13GB before the
first screen renders.

Also touched: `README.md`'s setup section inverts, `.env.example` documents the new defaults, and
`docs/specs/architecture.md` describes the default stack as including the model server.

## Sequencing

1. **ADR-028 and ADR-029** — nothing else starts first; the supersession is the decision the rest
   implements.
2. **STORY-078**, then **STORY-079** — the lean path can only be written against the new default.
3. **STORY-080** — CI last, because it consumes the override file STORY-079 creates.
4. Docs alongside their story, not in a sweep at the end.

## Testing

**The lean stack is the one that must be proved, because it is the one nothing else exercises.**
After this change the default path is what a developer runs constantly and CI never touches, and
the lean path is what CI runs and a developer rarely does. The plan verifies the lean stack comes
up, serves `/health`, and reports `extractor_adapter: null` on a rebuild — the field
`_record_adapters` already writes.

**The size gate must be watched failing.** Build the default images once, confirm the gate would
reject them at 16.6GB, then confirm the lean build passes it. A threshold nobody has seen reject
anything is not a gate.

**`docker compose down` stopping ollama is asserted, not assumed.** It is one of the three things
asked for, and it is the one most easily lost to a later refactor that reintroduces a profile.

## What this deliberately does not do

- **No change to `Settings` defaults.** `extractor_adapter` and `embedder_adapter` stay `"null"`
  in `config.py`. The default stack is a compose decision; a bare `uvicorn` run, and every test
  that constructs `Settings` directly, must keep working without a model server.
- **No new pull-time model choice.** `llama3.1:8b` stays, under ADR-020's provenance constraint.
- **No attempt to shrink the 16.6GB image.** ADR-021 records a route (a multi-stage sync layer,
  ~5GB) and it stays unexplored here; this design gives the size back rather than optimising it.
