"""A fixed set of parameterised queries, and the rule that picks one.

**Nothing here builds Cypher from a question.** The corpus is documents supplied
from outside this organisation, and a question can quote them. A component that
turned either into query text would be an injection sink: read-only execution
bounds the damage (ADR-009) but does not remove it, and "bounded remote code
execution" is not a security posture. So the query text is written here, in
advance, by a person — and a question can only *choose* among these and supply
values, which are bound as parameters and never interpolated (ADR-017).

Selection is deterministic pattern matching rather than a model. That is not a
placeholder for a model: it means a question cannot influence *which* query runs
except through rules visible in this file. A model-backed selector could be added
behind the same `Selection` return type later, and the guard that its answer must
name a template already in `TEMPLATES` is enforced by the route.
"""

import re
from dataclasses import dataclass, field

from policy_grapher.obligations import primary_anchor

GROUNDED_PASSAGES = "grounded_passages"


@dataclass(frozen=True)
class Template:
    """One thing this system knows how to be asked.

    `cypher` is None for the retrieval-backed template, which answers from the
    hybrid index rather than from a traversal.
    """

    name: str
    description: str
    cypher: str | None
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class Selection:
    name: str
    parameters: dict[str, str] = field(default_factory=dict)


_OBLIGATIONS_FOR_ACTOR = """
MATCH (v:DocumentVersion)-[:MANDATES]->(o:Obligation)
WHERE toLower(o.statement) CONTAINS toLower($actor)
   OR toLower(coalesce(o.actor, '')) CONTAINS toLower($actor)
--ANCHOR--
MATCH (d:Document)-[:HAS_VERSION]->(v)
RETURN o.statement    AS statement,
       o.modality     AS modality,
       d.name         AS document,
       v.version_id   AS version_id,
       anchor_chunk.section_path AS section_path,
       anchor_chunk.page         AS page,
       anchor_chunk.text         AS quote
ORDER BY d.name, page, statement
LIMIT $limit
"""

_IMPLEMENTS_FOR_DOCUMENT = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)-[:MANDATES]->(ours:Obligation)
WHERE toLower(d.name) CONTAINS toLower($document)
MATCH (ours)-[:IMPLEMENTS]->(higher:Obligation)
--ANCHOR--
MATCH (higher_doc:Document)-[:HAS_VERSION]->(higher_v:DocumentVersion)-[:MANDATES]->(higher)
RETURN higher.statement AS statement,
       higher.modality  AS modality,
       higher_doc.name  AS document,
       higher_v.version_id AS version_id,
       anchor_chunk.section_path AS section_path,
       anchor_chunk.page         AS page,
       anchor_chunk.text         AS quote
ORDER BY document, page, statement
LIMIT $limit
"""

_CHANGES_FOR_DOCUMENT = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)<-[:TO_VERSION]-(c:Change)
WHERE toLower(d.name) CONTAINS toLower($document)
MATCH (c)-[:AFFECTS]->(o:Obligation)
--ANCHOR--
RETURN c.kind || ': ' || c.statement AS statement,
       o.modality  AS modality,
       d.name      AS document,
       v.version_id AS version_id,
       anchor_chunk.section_path AS section_path,
       anchor_chunk.page         AS page,
       anchor_chunk.text         AS quote
ORDER BY page, statement
LIMIT $limit
"""


def _with_anchor(cypher: str, variable: str) -> str:
    return cypher.replace("--ANCHOR--", primary_anchor(variable, "anchor_chunk"))


TEMPLATES: dict[str, Template] = {
    "obligations_for_actor": Template(
        name="obligations_for_actor",
        description="Which duties the corpus places on a named actor.",
        cypher=_with_anchor(_OBLIGATIONS_FOR_ACTOR, "o"),
        parameters=("actor", "limit"),
    ),
    "implements_for_document": Template(
        name="implements_for_document",
        description="Which higher-level obligations a named document implements.",
        cypher=_with_anchor(_IMPLEMENTS_FOR_DOCUMENT, "higher"),
        parameters=("document", "limit"),
    ),
    "changes_for_document": Template(
        name="changes_for_document",
        description="What changed in the latest edition of a named document.",
        cypher=_with_anchor(_CHANGES_FOR_DOCUMENT, "o"),
        parameters=("document", "limit"),
    ),
    GROUNDED_PASSAGES: Template(
        name=GROUNDED_PASSAGES,
        description="Passages of the corpus that bear on the question.",
        cypher=None,
    ),
}

# Anchored to the start so a phrase buried in a longer sentence — including one
# quoted out of a document — cannot steer the choice.
_CHANGES = re.compile(r"what (?:has )?changed (?:in|to)\s+(?P<document>.+?)\s*\??$", re.IGNORECASE)
_IMPLEMENTS = re.compile(
    r"what does\s+(?P<document>.+?)\s+implement\s*\??$", re.IGNORECASE
)
_OBLIGES = re.compile(
    r"^(?:what obliges|what are the (?:duties|obligations|responsibilities) of|"
    r"who must|who shall)\s+(?P<actor>.+?)\s*\??$",
    re.IGNORECASE,
)


def select_template(question: str) -> Selection:
    """Choose a template and its parameters. Always returns a known name.

    The fallback is a real answer path, not an error: most questions are not one
    of three shapes, and `grounded_passages` answers them from the same corpus
    with the same citations.
    """
    text = (question or "").strip()

    changed = _CHANGES.search(text)
    if changed:
        return Selection("changes_for_document", {"document": changed["document"]})

    implements = _IMPLEMENTS.search(text)
    if implements:
        return Selection(
            "implements_for_document", {"document": implements["document"]}
        )

    obliges = _OBLIGES.search(text)
    if obliges:
        return Selection("obligations_for_actor", {"actor": obliges["actor"]})

    return Selection(GROUNDED_PASSAGES)
