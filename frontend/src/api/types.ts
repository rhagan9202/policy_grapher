export interface GraphNode {
  id: string
  label: string
  is_external: boolean
}

export interface GraphEdge {
  source: string
  target: string
}

export interface GraphOut {
  nodes: GraphNode[]
  edges: GraphEdge[]
  total_nodes: number
  returned_nodes: number
  truncated: boolean
}

export interface IngestResult {
  nodes_created: number
  relationships_created: number
  self_references_skipped: number
  suspected_duplicates: string[][]
}

export interface DocumentIn {
  name: string
}

export interface DocumentOut {
  slug: string
  name: string
  is_external: boolean
  references: string[]
  referenced_by: string[]
}

export interface ResetResult {
  nodes_deleted: number
  relationships_deleted: number
}

export interface QueryResult {
  rows: Record<string, unknown>[]
  returned_rows: number
  truncated: boolean
}
