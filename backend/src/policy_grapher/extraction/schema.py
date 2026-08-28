"""What an extracted obligation is, and how it is identified.

Validation lives here rather than at a provider boundary on purpose: a local
runtime's grammar and a hosted provider's JSON-schema mode are optimisations,
and the contract has to hold identically on both or the port is not a port.
"""

import hashlib
import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

WHITESPACE = re.compile(r"\s+")


class Modality(StrEnum):
    """How a duty was imposed — by a word, or by position.

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

    ASSIGNED is here because DoD writes its responsibilities sections as a role
    heading followed by lettered third-person verbs — "The USD(R&E): a. Executes
    ... b. Serves ..." — and grades their force nowhere. The duty is imposed by
    *position*. ADR-033 widened what this enum records to admit that: it is no
    longer "the word the document used" but how the duty arrived. Measured
    across the seven samples: 91 such duties, and none at all in the 2003 edition
    of DoDD 5000.01, which is what makes it a drafting convention rather than a
    permanent gap.

    The member records the mechanism, not the force. Ask `is_binding` for force.
    """

    SHALL = "SHALL"
    MUST = "MUST"
    WILL = "WILL"
    SHOULD = "SHOULD"
    MAY = "MAY"
    ASSIGNED = "ASSIGNED"


# The members that quote a word from the passage. Derived by subtraction, never
# listed: a sixth *word* added later joins this set automatically, whereas a
# hand-kept list is how a word modality silently escapes the rule below.
WORD_MODALITIES = frozenset(Modality) - {Modality.ASSIGNED}


# Which modalities impose a duty. Stated once, here, because the alternative is
# every consumer keeping its own list — and a consumer written before WILL existed
# keeps a list that silently under-counts rather than one that fails.
BINDING = frozenset(
    {Modality.SHALL, Modality.MUST, Modality.WILL, Modality.ASSIGNED}
)


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

    @model_validator(mode="after")
    def _modality_word_is_in_the_statement(self) -> ExtractedObligation:
        """The word the modality names has to appear in the sentence it labels.

        A modality is a claim about a word in the passage — `Modality` is closed
        precisely so that a model cannot invent one — and a statement that does
        not contain that word makes the claim about nothing.

        This is what the extraction prompt has asked for since PROMPT_VERSION 2,
        and asking was not enough. Measured on the live graph 2026-08-27, after a
        full rebuild under that prompt: 18 of 215 obligations were four words or
        fewer — "Be Responsive.", "Focus on Affordability.", "e. Emphasize
        Competition." — section headings labelled SHALL by a model with no SHALL
        to point at. Sprint 6 believed it had fixed this; the check it used
        compared exact strings without their trailing full stops, which the same
        prompt change had just started producing.

        Enforcing it here rather than in the prompt makes it deterministic, and
        [ADR-030](../../../docs/specs/adr/ADR-030-a-rejected-item-costs-itself-not-its-chunk.md)
        is what makes it affordable: an item rejected for this now costs itself
        rather than every obligation that shared its chunk.

        Word boundaries, not substrings — "General Marshall commanded the Army"
        contains "shall" and imposes nothing.

        ADR-033 restated this rule rather than granting an exception to it: *if*
        a modality names a word, the statement must contain that word. ASSIGNED
        falls outside by naming none — by construction, not by appearing on a
        list of exceptions, which is how such a check rots.
        """
        if self.modality not in WORD_MODALITIES:
            return self
        if not re.search(rf"\b{self.modality.value}\b", self.statement, re.IGNORECASE):
            raise ValueError(
                f"statement does not contain its modality {self.modality.value!r}: "
                f"{self.statement!r}"
            )
        return self

    @model_validator(mode="after")
    def _an_assigned_duty_names_its_actor(self) -> ExtractedObligation:
        """ADR-033's schema half of the structural guard.

        A value naming no word cannot be checked against the passage the way the
        other five are, so it is guarded by structure instead. A positional duty
        is an assignment *to somebody*: without an actor there is no position,
        and ASSIGNED becomes the escape hatch that puts section headings back in
        the graph as duties. The other half — that the section is one that
        assigns responsibilities — needs to know where the chunk came from, so it
        lives in `validate_extracted` rather than here.
        """
        if self.modality is Modality.ASSIGNED and not (self.actor or "").strip():
            raise ValueError(
                "an ASSIGNED obligation must name the actor it is assigned to"
            )
        return self

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
