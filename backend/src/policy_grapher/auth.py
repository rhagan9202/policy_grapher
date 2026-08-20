"""Bearer-token authentication.

Per ADR-008 the audience is no longer assumed Cypher-fluent or trusted, so every
mutating route needs a principal. Token verification is deliberately one function:
replacing it with an OIDC verifier should not touch a single call site.
"""

import hashlib
import hmac

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from policy_grapher.config import Settings
from policy_grapher.dependencies import get_app_settings


class Principal(BaseModel):
    """Who is making the request. Recorded as the actor on any decision they take."""

    name: str


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_DIGEST_LENGTH = 64


def _is_digest(candidate: str) -> bool:
    """Whether a *configured* value has the shape of a SHA-256 hex digest.

    `hmac.compare_digest` raises TypeError on a non-ASCII string, so a single
    mistyped entry used to abort the scan and 401-turned-500 every route. ADR-008
    Decision 3 promises the opposite: one bad line must not take down the valid
    tokens beside it. This looks only at configuration, never at the presented
    token, so it adds no data-dependent branch an attacker can time.
    """
    return len(candidate) == _DIGEST_LENGTH and _HEX_DIGITS.issuperset(candidate)


def verify_token(token: str, configured: str) -> Principal | None:
    """Resolve a bearer token to a principal, or None.

    `configured` is `name:digest` pairs, comma-separated. An entry without a `:`, or
    whose digest is not 64 hex characters, is skipped: a malformed line disables
    itself and nothing else (ADR-008 Decision 3). Comparison is constant-time so a
    timing signal cannot enumerate valid tokens. Every well-formed entry is checked
    even after a match, for the same reason.
    """
    presented = token_digest(token)
    found: Principal | None = None
    for entry in configured.split(","):
        name, separator, digest = entry.partition(":")
        if not separator:
            continue
        digest = digest.strip()
        if not _is_digest(digest):
            continue
        if hmac.compare_digest(digest, presented) and found is None:
            found = Principal(name=name.strip())
    return found


def require_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_app_settings),
) -> Principal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=401,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = verify_token(token, settings.api_tokens)
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal
