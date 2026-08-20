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
