# ADR-018: The dev proxy forwards writes, and a header is the guard

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

## Context

[ADR-008](ADR-008-authenticated-non-cypher-audience.md) authenticated every route but
`/health`. The browser app has no login and holds no token — by design, so that a token
never enters JavaScript — so the vite dev server injects one server-side into the requests
it proxies. That is a development affordance, stated as such at the call site.

Phase 0's whole-branch review found that injecting on every request made port 5173 an
unauthenticated bypass of the gate ADR-008 had just built. `POST /api/reset` takes no body
and no custom header, which makes it a CORS *simple request*: any page the developer
happened to visit could fire `fetch('http://localhost:5173/api/reset', {method: 'POST',
mode: 'no-cors'})` and wipe the graph. The browser blocks reading the response, not sending
it. Phase 0 closed that by injecting only on `GET`, which cost nothing at the time — the UI
issued only reads.

That is no longer true. The review queue in DI-2 phase 4 exists to record a human verdict,
which is a `POST`. A GET-only proxy cannot serve a UI that writes, so the question came back:
how does a UI write authenticate?

## Options considered

**Keep GET-only and build a real login.** Correct destination, wrong time. It means a session
store, a token lifetime, a logout path and a decision about the identity provider — the work
ADR-008 deliberately deferred because DI-2 needs an `actor` for `:LinkDecision`, not an
identity provider. It would block phase 4 on an unrelated build.

**Widen to all methods, unguarded.** Restores the drive-by. A page the developer visits
could delete the corpus. Cheap, and the cheapness is the trap: nothing about the failure is
visible until it happens.

**Widen to all methods, guarded by a header the proxy requires.** Injection is conditional on
`x-policy-grapher-ui: 1`. A cross-origin page cannot set a custom header without triggering a
CORS preflight, and `mode: 'no-cors'` — the only mode that lets a page fire a request whose
response it cannot read — forbids custom headers outright. So the drive-by gets no token.

## Decision

The dev proxy forwards **every method** and injects the bearer token only for requests
carrying `x-policy-grapher-ui: 1` (`frontend/vite.config.ts`). The API client sends that
header on every request (`frontend/src/api/client.ts`), and three tests pin it — including
one asserting it on a write, which is the case this ADR exists for.

The guard is the header, not the method.

## Consequences

**Makes easy.** A UI that writes: the phase 4 review queue can POST a verdict, and phase 6's
`POST /ask` works, with no login flow and no token in browser storage. The property ADR-008
cared about is intact — the token still never enters JavaScript.

**Makes hard.** Removing the header silently breaks every request, which is why it is pinned
by tests rather than left to a comment. Any future client of this API through the proxy has
to know to send it.

**Commits us to.** An accepted residual: **the header stops a browser, not a local process.**
`curl -H 'x-policy-grapher-ui: 1' -X POST localhost:5173/api/reset` still wipes the graph.
The only bound on that is `docker-compose.yml` publishing the port as `127.0.0.1:5173`, so
the caller is already on the machine — the same trust boundary that already lets them read
`.env`. This is accepted knowingly, not overlooked.

That residual is the reason this stays a *development* affordance. It is sound while the
threat model is "a developer's laptop, and pages that developer visits". It is not sound the
moment the UI is served to someone who is not the person who ran `init-env.sh`. **Revisit
when the frontend is served to a second user** — that is this ADR's expiry condition, and it
arrives with the multi-user deployment the DI-2 design already names as the eventual target.
