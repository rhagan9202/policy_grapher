from typing import Literal

from pydantic import BaseModel, Field


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
