from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    filename: str


class IngestResult(BaseModel):
    nodes_created: int
    relationships_created: int
    self_references_skipped: int
    suspected_duplicates: list[list[str]] = Field(default_factory=list)


class ResetResult(BaseModel):
    nodes_deleted: int
    relationships_deleted: int


class GraphNode(BaseModel):
    id: str
    label: str
    reference_role: str | None = None
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


class DocumentOut(BaseModel):
    slug: str
    name: str
    reference_role: str | None
    is_external: bool
    references: list[str] = Field(default_factory=list)
    referenced_by: list[str] = Field(default_factory=list)


class DocumentIn(BaseModel):
    name: str = Field(min_length=1)
    reference_role: str = Field(min_length=1)


class QueryRequest(BaseModel):
    cypher: str = Field(min_length=1)
