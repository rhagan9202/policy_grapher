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


def verify_token(token: str, configured: str) -> Principal | None:
    """Resolve a bearer token to a principal, or None.

    `configured` is `name:digest` pairs, comma-separated. Comparison is constant-time
    so a timing signal cannot enumerate valid tokens. Every entry is checked even
    after a match, for the same reason.
    """
    presented = token_digest(token)
    found: Principal | None = None
    for entry in configured.split(","):
        name, separator, digest = entry.partition(":")
        if not separator:
            continue
        if hmac.compare_digest(digest.strip(), presented) and found is None:
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
