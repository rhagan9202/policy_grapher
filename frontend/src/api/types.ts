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

export interface DocumentVersionOut {
  version_id: string
  effective_date: string | null
  checksum: string
  source_uri: string
  supersedes: string | null
}

/** One side of a proposed link, with enough context to decide from. */
export interface ObligationCitation {
  obligation_id: string
  statement: string
  modality: string
  document: string
  section_path: string[]
  page: number
}

export interface ReviewItem {
  source: ObligationCitation
  target: ObligationCitation
  confidence: number
  rationale: string
  proposer: string
}

export type Verdict = 'approve' | 'reject'

export interface TriageCitation {
  obligation_id: string
  statement: string
  document: string
  section_path: string[]
  page: number
}

export interface TriageRow {
  change_id: string
  kind: string
  score: number
  modality: string
  summary: string
  previous_statement: string | null
  ours: TriageCitation
  higher: TriageCitation
}

export interface TriageOut {
  from_version_id: string
  to_version_id: string
  rows: TriageRow[]
  /** Changes found at all — rows only covers those reaching a reviewed link. */
  total_changes: number
  /**
   * Changes with no reviewed IMPLEMENTS path. Must be shown, never hidden: an
   * empty `rows` with a non-zero count here means "nothing linked yet", which is
   * a different thing from "nothing affected" (ADR-015).
   */
  unlinked_changes: number
}

export interface Citation {
  document: string
  section_path: string[]
  page: number
  quote: string
}

export interface Answer {
  answer: string
  citations: Citation[]
  template_used: string
}
