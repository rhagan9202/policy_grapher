# ADR-010: Secrets leave the repository

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

SPEC-001 committed `.env` deliberately, with a working Neo4j password inside it, so that a
clean clone ran with `docker compose up` and no manual step
([Environment Variables](../SPEC-001-di-1-policy-grapher.md)). That trade accepted one cost
explicitly: the password was public by construction, and the README, architecture doc, and
SPEC-001 itself all said so, on the grounds that the deployment target was local-only and the
password protected nothing but a disposable development database.

[ADR-008](ADR-008-authenticated-non-cypher-audience.md) changes what that database sits
behind. The app is now authenticated — every route but `/health` requires a bearer token —
and DI-2 targets a hosted deployment, the same trigger ADR-008 and
[ADR-009](ADR-009-query-is-read-only-and-bounded.md) already named. Once the target is no
longer strictly local-only, a committed password stops being an acceptable trade: a public
Neo4j credential next to an authenticated API is a hole in the wall the API just built.
`API_TOKENS` — the bearer-token allow-list ADR-008 introduced — has the same problem in a
different shape: it ships **empty** in a committed `.env`, so a clean clone authenticates
nobody, and nothing populates it without a manual step that SPEC-001's one-command promise
was written to avoid.

## Options considered

**Keep committing `.env`, generate nothing.** Preserves the one-command clone but keeps
shipping a public password and an empty token allow-list — the exact problem this ADR
exists to close, now sitting behind an authenticated API instead of an open one.

**Require operators to hand-configure secrets before first run.** Removes the public
password without generating anything, but reintroduces the manual step SPEC-001 traded the
password's exposure to avoid, and an operator who skips it gets a backend that cannot reach
Neo4j or an `API_TOKENS` that authenticates nobody — silent failure, not a clear error.

**Generate secrets locally, commit only a template.** Chosen. `scripts/init-env.sh` writes a
random Neo4j password and API token into an untracked `.env`, derived from `.env.example`.
The one-command property SPEC-001 valued survives as two commands —
`./scripts/init-env.sh && docker compose up --build` — instead of one, which is the cost
this ADR accepts in exchange for not shipping a public credential.

## Decision

1. **`.env` is generated, not committed.** `scripts/init-env.sh` is the only way to produce
   it: it refuses to overwrite an existing `.env`, generates a random Neo4j password and a
   random API token, computes the token's SHA-256 digest with the same algorithm
   `auth.token_digest` uses, and writes both into `.env` from the `.env.example` template.
   `.env` is now in `.gitignore`.

2. **One generated token, two forms, one source.** The token is written twice: as
   `API_TOKENS=dev:<digest>` (the backend's allow-list, matching what ADR-008's
   `verify_token` expects) and as `API_TOKEN=<token>` (the same token in plaintext, read only
   by the vite dev proxy so the browser app can send `Authorization: Bearer <token>` without
   the token ever reaching browser JavaScript). Both come from the one token
   `init-env.sh` generates — a second, independently-minted token in either slot would
   authenticate nothing.

3. **The previously committed password is compromised, and that is accepted.** It remains
   in git history and cannot be un-published. This is judged harmless because it never
   protected anything but a local development Neo4j instance behind no other gate; anyone
   who cloned the repository already had it. Anyone still running a stack initialized from
   that password should re-run `init-env.sh` against a fresh `.env` — and must also
   `docker compose down -v` first. `NEO4J_AUTH` only initialises a *new* data volume; it
   does not re-key an existing one, so a generated password against a pre-existing
   `neo4j-data` volume leaves the backend failing `verify_connectivity()` in a restart
   loop. Dropping the volume is the whole fix, and the corpus re-ingests from the CSV.

4. **Generated tokens remain a stopgap, not an identity provider.** `init-env.sh` produces
   exactly one principal (`dev`). This is the same deliberate limitation ADR-008 already
   named and accepted: real multi-user login, token rotation, and revocation without a
   restart are out of scope until the deployment actually needs them.

## Consequences

**Makes easy.** A clean clone still runs from a public repository with no secret
committed to it going forward — the password already in git history stays there, per
Decision 3. Re-running `init-env.sh` after deleting `.env` produces a fresh password
and token with no code change. The UI works out of the box against a freshly generated
token, closing the gap ADR-008's introduction opened (an authenticated backend with no way
for the browser app to authenticate).

**Makes hard.** First run is two commands instead of one, and a lost `.env` means
re-generating secrets rather than recovering them — there is no backup or recovery path,
by design, since nothing is stored outside the local file. Sharing a token with a
teammate now means sending it out of band; nothing in the repository does that for you.

**Commits us to.** Every future contributor runs `init-env.sh` once; documentation
(README, architecture.md, SPEC-001) all had to be updated in this same change to stop
telling readers the password is public by construction, and any future onboarding docs
need to say the same thing this ADR does.

**Revisit when** an identity provider replaces static tokens (ADR-008's own revisit
trigger) — at that point secret generation for `API_TOKENS`/`API_TOKEN` goes away
alongside `verify_token`, though the Neo4j password half of this ADR persists
independently.
