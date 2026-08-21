from typing import Literal

from pydantic import BaseModel, Field, field_validator


class IngestRequest(BaseModel):
    filename: str


class IngestResult(BaseModel):
    source: Literal["manifest"] = "manifest"
    nodes_created: int
    relationships_created: int
    self_references_skipped: int
    suspected_duplicates: list[list[str]] = Field(default_factory=list)


class DocumentRef(BaseModel):
    slug: str
    name: str


class DocumentIngestResult(BaseModel):
    source: Literal["document"] = "document"
    format: str
    document: DocumentRef
    nodes_created: int
    relationships_created: int
    references_attributed: int
    references_unattributed: list[str] = Field(default_factory=list)
    self_references_skipped: int


class ResetResult(BaseModel):
    nodes_deleted: int
    relationships_deleted: int


class GraphNode(BaseModel):
    id: str
    label: str
    is_external: bool


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    returned_nodes: int
    truncated: bool


type JSONScalar = str | int | float | bool
type JSONValue = JSONScalar | None | list[JSONValue] | dict[str, JSONValue]

JSON_SCALARS = (str, int, float, bool)


class QueryResult(BaseModel):
    rows: list[dict[str, JSONValue]]
    returned_rows: int
    truncated: bool


class DocumentOut(BaseModel):
    slug: str
    name: str
    is_external: bool
    references: list[str] = Field(default_factory=list)
    referenced_by: list[str] = Field(default_factory=list)
    # How many editions this document has. Zero for the great majority — an
    # externally cited document has no ingested text (STORY-040).
    version_count: int = 0


class DocumentVersionOut(BaseModel):
    version_id: str
    effective_date: str | None
    checksum: str
    source_uri: str
    supersedes: str | None


class DocumentIn(BaseModel):
    name: str = Field(min_length=1)


class QueryRequest(BaseModel):
    cypher: str = Field(min_length=1)


class ChunkOut(BaseModel):
    chunk_id: str
    text: str
    page: int
    section_path: list[str]
    ordinal: int


class ObligationCitationOut(BaseModel):
    """One side of a proposed link, with enough context to decide from.

    The citation fields are not decoration: a reviewer asked whether one clause
    implements another cannot answer without knowing which document each comes
    from and where in it to go and read.
    """

    obligation_id: str
    statement: str
    modality: str
    document: str
    section_path: list[str]
    page: int


class ReviewItemOut(BaseModel):
    source: ObligationCitationOut
    target: ObligationCitationOut
    confidence: float
    rationale: str
    proposer: str


class VerdictIn(BaseModel):
    """A reviewer's decision.

    Deliberately carries no `actor`. The actor is the authenticated principal and
    nothing else — a client-supplied one would let anyone record a decision as
    anyone, which makes the audit trail worthless. `extra="ignore"` (the default)
    means a body that sends one is accepted and the field discarded.
    """

    verdict: str = Field(min_length=1)
    rationale: str = ""


class TriageCitationOut(BaseModel):
    """One side of a triage row, sourced. Nothing in a triage response is
    unattributed: a row naming a policy without saying which passage of it is
    affected would send a reviewer hunting."""

    obligation_id: str
    statement: str
    document: str
    section_path: list[str]
    page: int


class TriageRowOut(BaseModel):
    change_id: str
    kind: str
    score: float
    modality: str
    summary: str
    previous_statement: str | None
    ours: TriageCitationOut
    higher: TriageCitationOut


class TriageOut(BaseModel):
    """`from_version_id` is echoed back because it may have been defaulted: a
    caller who omitted it needs to know which earlier edition the answer is about.

    `unlinked_changes` is what keeps an empty `rows` honest. Without it, "nothing
    you own is affected" and "nothing has been reviewed yet, so this cannot see
    anything" are the same response, and one of them is a false all-clear.
    """

    from_version_id: str
    to_version_id: str
    rows: list[TriageRowOut]
    total_changes: int
    unlinked_changes: int


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class CitationOut(BaseModel):
    """Where a claim came from, precisely enough to go and read it."""

    document: str
    section_path: list[str]
    page: int
    quote: str


class AnswerOut(BaseModel):
    """An answer and everything it rests on.

    `citations` is empty only when `answer` says the corpus does not address the
    question. There is no third state — an answer with no citation behind it is a
    hallucination with good grammar (ADR-017).
    """

    answer: str
    citations: list[CitationOut]
    template_used: str


class RebuildRequest(BaseModel):
    """What to compare the rebuilt edition against.

    Naming candidates is the only way proposals get made: nothing in the graph
    records which documents are higher-tier (ADR-015 drops tier distance from
    ranking for exactly that reason), so the caller states it and the route does
    not guess. Empty — including an omitted body — means rebuild only.
    """

    candidate_version_ids: list[str] = Field(default_factory=list)


class RebuildStarted(BaseModel):
    run_id: str
    version_id: str
    # Echoed back so the response says what the run will compare against, rather
    # than leaving the caller to infer it from an empty review queue later.
    candidate_version_ids: list[str] = Field(default_factory=list)


class RebuildStatus(BaseModel):
    """What a poller sees.

    `counts` is populated only once the run finishes and `error` only if it
    failed. Both empty, with `state` still in progress, is the normal mid-run
    reading.
    """

    run_id: str
    version_id: str
    state: str
    chunks_done: int = 0
    chunks_total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
