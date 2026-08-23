"""What an extracted obligation is, and how it is identified.

Validation lives here rather than at a provider boundary on purpose: a local
runtime's grammar and a hosted provider's JSON-schema mode are optimisations,
and the contract has to hold identically on both or the port is not a port.
"""

import hashlib
import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

WHITESPACE = re.compile(r"\s+")


class Modality(StrEnum):
    """The word the document used to impose a duty.

    Still closed, and for the original reason: SHALL misread as SHOULD downgrades
    a binding duty to advice, silently, so an adapter that invents a value must
    fail loudly. What changed in ADR-025 is which words are in it.

    WILL is here because the corpus uses it. Across the seven samples `will`
    appears 458 times against `shall` 93, and the split is generational rather
    than incidental: the 2003 edition of DoDD 5000.01 uses `shall` 92 times and
    `must` never, while its 2020 re-issue uses `shall` zero times and `will` 44.
    DoD's plain-language drafting replaced the directive `shall` with `will`, so
    on five of the seven samples an extractor obeying the old set could only
    report a minority of the document's duties.

    The member records the *word*, not its force. Ask `is_binding` for the force.
    """

    SHALL = "SHALL"
    MUST = "MUST"
    WILL = "WILL"
    SHOULD = "SHOULD"
    MAY = "MAY"


# Which modalities impose a duty. Stated once, here, because the alternative is
# every consumer keeping its own list — and a consumer written before WILL existed
# keeps a list that silently under-counts rather than one that fails.
BINDING = frozenset({Modality.SHALL, Modality.MUST, Modality.WILL})


class ExtractedObligation(BaseModel):
    statement: str = Field(min_length=1)
    modality: Modality
    actor: str | None
    deadline: str | None
    conditions: str | None
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def is_binding(self) -> bool:
        """Whether this imposes a duty, as opposed to advising or permitting.

        Derived rather than extracted: the model reports the word it saw, and what
        that word obliges is this project's reading of it, recorded in ADR-025.
        Asking a model to decide bindingness would make the answer vary by model.
        """
        return self.modality in BINDING

    @field_validator("statement")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("statement must not be blank")
        return value


def normalize(statement: str) -> str:
    """The form identity is computed over.

    Case and whitespace only. A reflowed line or a changed indent must not
    orphan a human decision, but a changed *word* must — that is a different
    obligation, and Phase 5 needs to see it as one.
    """
    return WHITESPACE.sub(" ", statement).strip().casefold()


def obligation_id(version_id: str, section_path: list[str], statement: str) -> str:
    key = f"{version_id}|{'/'.join(section_path)}|{normalize(statement)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
