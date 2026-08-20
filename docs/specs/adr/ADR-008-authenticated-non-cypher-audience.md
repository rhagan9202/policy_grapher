# ADR-008: Bearer tokens authenticate a non-Cypher-fluent audience

**Status:** Accepted · **Date:** 2026-08-20 · **Deciders:** Project owner

*Frozen once accepted. To change this decision, write a new ADR and mark this one superseded.*

**Supersedes [ADR-001](ADR-001-demo-assumes-cypher-fluent-users.md).** ADR-001 assumed the
demo's users were comfortable writing Cypher, and named its own revisit trigger explicitly:
"Revisit when LLM query construction starts. That work supersedes this ADR's audience
assumption." DI-2 is that work — [ADR-009](ADR-009-query-is-read-only-and-bounded.md) already
bounds what `POST /query` can do; this ADR addresses who is allowed to call it at all.

## Context

ADR-001 accepted an unauthenticated, Cypher-fluent audience for one reason: DI-1 was a local
demo, and every caller was a technical human at a keyboard. ADR-001 itself flagged the
consequence of that choice plainly — `POST /query` runs arbitrary Cypher "with no auth and
open CORS," and called authentication and query constraint "prerequisites before that layer
ships, not afterthoughts," naming the layer as LLM-constructed queries specifically.

DI-2 is that layer. Its [design](../../superpowers/specs/2026-08-20-di-2-design.md) targets a
hosted deployment and STORY-019 names authentication as an [ADR-004](ADR-004-unrestricted-cypher-in-di-1.md)
prerequisite that also supplies "the `actor` on every `:LinkDecision`" — human review of
machine-proposed graph edits, arriving later in DI-2. Two things are therefore both true at
once: the audience is no longer trusted or Cypher-fluent (an LLM, or a hosted user, may be the
caller), and a piece of state that did not exist in DI-1 — *who took this action* — now needs
somewhere to live before review decisions can record it.

This is Phase 0 of the DI-2 security gate. [ADR-009](ADR-009-query-is-read-only-and-bounded.md)
already constrains what an authenticated caller's queries can do (read-only, timed, capped).
This ADR is the other half: constraining who is a caller in the first place, and giving that
identity a name — `Principal` — that later work (review decisions, audit trails) can attach
itself to without inventing a second notion of identity.

Applying authentication to routes is deliberately out of this ADR's scope. Wiring
`Depends(require_principal)` into the routers that need it is separate follow-on work; this
decision is about what a principal *is* and how a token resolves to one.

## Options considered

**OIDC or a hosted identity provider.** The eventual right answer for a multi-user,
possibly-external-facing deployment — delegated login, token refresh, revocation, and no
password or token material for this project to manage. Rejected for *now*, not rejected
outright: DI-2 needs an `actor` string to put on a `:LinkDecision`, not a login flow, and
adopting an IdP without real multi-tenant requirements would be choosing infrastructure on a
guess. `python-jose` or a similar library implies the same premature choice.

**Static bearer tokens, hashed at rest, compared in constant time.** Chosen. Configuration is
`name:sha256hex` pairs in one environment variable — `alice:9f86d0...`. No token is stored in
plaintext, no session state, and verification is deliberately isolated in one function
(`verify_token`) so an OIDC or JWT verifier can replace it later without touching any call
site. This is a smaller, honest match for what DI-2 actually needs: an identity to name as
`actor`, provisioned by whoever operates the deployment.

**Plaintext tokens compared with `==`.** Rejected outright, not deferred. `==` on strings
short-circuits on the first mismatched byte, which leaks how many leading characters of a
guess were correct through response timing — a real attack against any secret comparison, not
a theoretical one. Storing tokens in plaintext also means a config leak or log line discloses
working credentials directly, rather than a hash an attacker still has to invert.

## Decision

1. **A `Principal` is a name.** `Principal(name: str)` is the entire shape. It is what
   `require_principal` returns and what later work records as the `actor` on a review
   decision — nothing more is speculatively added ahead of a concrete need for it.

2. **Tokens are opaque bearer strings, hashed at rest.** `token_digest` is SHA-256 over the
   UTF-8 token. Configuration (`Settings.api_tokens`) holds `name:digest` pairs,
   comma-separated, never the raw token.

3. **Verification is one function, and it fails closed.** `verify_token(token, configured)`
   returns a `Principal` or `None`. Empty configuration matches nothing — an operator who
   forgets to set `API_TOKENS` gets universal denial, not universal access. A malformed entry
   (no `:`) is skipped rather than raising, so one bad line in the configuration doesn't take
   down every valid token alongside it.

4. **Comparison is constant-time and exhaustive.** Digests are compared with
   `hmac.compare_digest`, and every configured entry is checked even after a match is found,
   so response timing cannot reveal how many entries exist or where in the list a match
   landed.

5. **The FastAPI wiring is a single dependency.** `require_principal` reads the `Authorization`
   header, requires a `Bearer` scheme, and raises `401` with a `WWW-Authenticate: Bearer`
   header on anything that doesn't resolve to a `Principal`. It is not attached to any route
   in this change — that is separate follow-on work.

## Consequences

**Makes easy.** `POST /link-decisions` (or whatever review-decision route eventually lands)
has an obvious source for `actor`: whatever `require_principal` returned on that request. A
second bearer token for a second reviewer is one more `name:digest` pair in configuration, no
code change. Swapping the verifier for OIDC later is a rewrite of `verify_token`'s body, not a
search-and-replace across every router.

**Makes hard.** Token issuance, rotation, and revocation are entirely manual — an operator
computes a digest, edits the environment variable, and restarts the service. There is no
per-token expiry and no way to revoke one token without touching the whole configuration
string. This is acceptable for DI-2's operator-provisioned scale and would not be acceptable
past it.

**Commits us to.** Every mutating route this reaches eventually depends on `Principal`, so its
shape (`name: str`) needs to hold up under whatever OIDC or JWT claims replace `verify_token`
later — a `sub` or `email` claim maps onto `name` without difficulty, so this is not expected
to be a load-bearing constraint, but it is one worth naming rather than discovering by
accident.

**Revisit when** the deployment needs real multi-user login (self-service accounts, token
expiry, revocation without a restart) rather than an operator handing out a handful of static
tokens. At that point `verify_token` is replaced; nothing that calls `require_principal`
should need to change.
