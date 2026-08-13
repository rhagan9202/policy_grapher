"""Deterministic, URL-safe identifiers for documents.

Slug assignment is a pure function of the *set* of names, not of the order they
arrive in. When two names normalise to the same base slug, every contender gets a
hash suffix — so no document's URL depends on which row was ingested first.
See ADR-003.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable

MAX_SLUG_LENGTH = 80
FALLBACK_SLUG = "document"

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def base_slug(name: str, maxlen: int = MAX_SLUG_LENGTH) -> str:
    """Casefold, hyphenate runs of non-alphanumerics, trim, truncate."""
    slug = _NON_ALPHANUMERIC.sub("-", name.casefold()).strip("-")
    slug = slug[:maxlen].strip("-")
    return slug or FALLBACK_SLUG


def hash_suffix(name: str) -> str:
    """First 8 hex characters of the SHA-256 of the full, untruncated name."""
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]


def assign_slugs(names: Iterable[str]) -> dict[str, str]:
    """Map each distinct name to its slug, resolving contested bases by hash."""
    by_base: dict[str, list[str]] = defaultdict(list)
    for name in sorted(set(names)):
        by_base[base_slug(name)].append(name)

    assigned: dict[str, str] = {}
    for base, contenders in by_base.items():
        if len(contenders) == 1:
            assigned[contenders[0]] = base
        else:
            for name in contenders:
                assigned[name] = f"{base}-{hash_suffix(name)}"
    return assigned
