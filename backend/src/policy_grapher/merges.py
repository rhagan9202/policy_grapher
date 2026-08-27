"""Reconciling two records of one document — STORY-031, ADR-032.

A merge is a *recorded decision*, replayed after every ingest, not an edit. A
manifest naming both spellings recreates the node that was merged away, and an
edit would be undone silently on the next ingest — the failure `:LinkDecision`
exists to prevent for links, in a new place.

Only documents with nothing hanging off them may be merged. A document carrying an
edition raises ADR-027's questions about re-keying obligations whose ids hash a
`version_id`, and that is a separate item. Refusing loudly is the boundary.
"""


from neo4j import ManagedTransaction


class MergeRefused(ValueError):
    """The merge was not attempted, and nothing was changed."""


# Keyed on *names*, not slugs, and the difference is load-bearing. ADR-005 gives
# the incumbent the bare slug and the newcomer a suffix, so deleting the loser
# frees a slug the next ingest may hand to a different node — a merge recorded by
# slug stops matching the thing it merged away. A name comes from the manifest and
# does not move. Found by the re-ingest test, which is the only place it shows.
HAS_EDITIONS = """
MATCH (d:Document) WHERE d.name IN [$survivor, $merged]
RETURN d.name AS name, EXISTS { MATCH (d)-[:HAS_VERSION]->() } AS has_editions
"""

RECORD_MERGE = """
MERGE (m:DocumentMerge {key: $key})
SET m.survivor = $survivor,
    m.merged   = $merged,
    m.verdict  = 'same',
    m.actor    = $actor,
    m.at       = datetime()
"""

RECORD_DIFFERENT = """
MERGE (m:DocumentMerge {key: $key})
SET m.survivor = $first,
    m.merged   = $second,
    m.verdict  = 'different',
    m.actor    = $actor,
    m.at       = datetime()
"""

# Repoint, then delete — and only where both nodes are actually present, so
# replaying a merge whose loser does not exist is a no-op rather than an error.
APPLY_ONE = """
MATCH (m:DocumentMerge {verdict: 'same'})
MATCH (survivor:Document {name: m.survivor})
MATCH (loser:Document {name: m.merged})
CALL (survivor, loser) {
    MATCH (citer)-[r:REFERENCES]->(loser)
    WHERE citer <> survivor
    MERGE (citer)-[:REFERENCES]->(survivor)
    DELETE r
}
CALL (survivor, loser) {
    MATCH (loser)-[r:REFERENCES]->(target)
    WHERE target <> survivor
    MERGE (survivor)-[:REFERENCES]->(target)
    DELETE r
}
DETACH DELETE loser
RETURN count(*) AS applied
"""

RESOLVED_PAIRS = """
MATCH (m:DocumentMerge)
RETURN m.survivor AS a, m.merged AS b
"""


def _key(first: str, second: str) -> str:
    """Order-independent, so deciding about (a, b) also decides about (b, a)."""
    return "|".join(sorted((first, second)))


def record_merge(
    tx: ManagedTransaction, *, survivor: str, merged: str, actor: str
) -> None:
    """Record that two documents are the same. Applied by `apply_merges`."""
    if survivor == merged:
        raise MergeRefused("A document cannot be merged into itself.")

    carrying = {
        record["name"]: record["has_editions"]
        for record in tx.run(HAS_EDITIONS, survivor=survivor, merged=merged)
    }
    missing = {survivor, merged} - set(carrying)
    if missing:
        raise MergeRefused(f"No document named {sorted(missing)!r}.")

    with_text = sorted(slug for slug, has in carrying.items() if has)
    if with_text:
        raise MergeRefused(
            f"{with_text!r} carries an edition, and merging documents that hold "
            f"text is not attempted (ADR-032): an obligation's id hashes its "
            f"version_id, so its owner cannot simply change."
        )

    tx.run(
        RECORD_MERGE,
        key=_key(survivor, merged),
        survivor=survivor,
        merged=merged,
        actor=actor,
    ).consume()


def record_not_duplicates(
    tx: ManagedTransaction, *, first: str, second: str, actor: str
) -> None:
    """Record that a flagged pair is two different documents, so it is not asked
    about again — the same reason a rejection is stored beside an approval."""
    tx.run(
        RECORD_DIFFERENT, key=_key(first, second), first=first, second=second, actor=actor
    ).consume()


def apply_merges(tx: ManagedTransaction) -> int:
    """Re-apply every recorded merge. Idempotent, and called after every ingest.

    Returns how many were applied — zero on the common path, where either nothing
    is recorded or every merge is already in effect.
    """
    record = tx.run(APPLY_ONE).single()
    return record["applied"] if record else 0


def unresolved_duplicates(
    tx: ManagedTransaction, *, flagged: list[tuple[str, ...]]
) -> list[tuple[str, ...]]:
    """The flagged groups nobody has ruled on yet.

    Takes the names ingest flagged rather than re-deriving them: the detector
    lives in `sources/manifest.py`, and a second one here would let the screen and
    the ingest disagree about what is suspicious. Names throughout, for the same
    reason merges are recorded by name.
    """
    decided = {_key(record["a"], record["b"]) for record in tx.run(RESOLVED_PAIRS)}
    return [
        group for group in flagged if _key(*sorted(group)[:2]) not in decided
    ]
