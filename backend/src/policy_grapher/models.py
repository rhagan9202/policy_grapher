from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    filename: str


class IngestResult(BaseModel):
    nodes_created: int
    relationships_created: int
    self_references_skipped: int
    suspected_duplicates: list[list[str]] = Field(default_factory=list)


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
