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

// `POST /ingest` returns one of two shapes and says which in `source`. The type
// modelled only the manifest one until STORY-043, so a PDF ingest resolved to an
// object the compiler believed had no `document` and no `references_unattributed`.
// Nothing caught it because nothing called `ingest()`.
export interface ManifestIngestResult {
  source: 'manifest'
  nodes_created: number
  relationships_created: number
  self_references_skipped: number
  suspected_duplicates: string[][]
}

export interface DocumentIngestResult {
  source: 'document'
  format: string
  document: { slug: string; name: string }
  nodes_created: number
  relationships_created: number
  references_attributed: number
  references_unattributed: string[]
  self_references_skipped: number
}

export type IngestResult = ManifestIngestResult | DocumentIngestResult

export interface DocumentIn {
  name: string
}

export interface DocumentOut {
  slug: string
  name: string
  is_external: boolean
  references: string[]
  referenced_by: string[]
  /** Editions this document has. Zero for the great majority — an externally
   *  cited document has no ingested text, so it can never be triaged. */
  version_count: number
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

export interface ChunkOut {
  chunk_id: string
  text: string
  page: number
  section_path: string[]
  ordinal: number
}

// The rebuild routes have existed since STORY-048 and `client.ts` modelled neither,
// so sprint 4's whole deliverable was unreachable from the UI (STORY-061).
export interface RebuildStarted {
  run_id: string
  version_id: string
  candidate_version_ids: string[]
}

export interface RebuildStatus {
  run_id: string
  version_id: string
  state: string
  chunks_done: number
  chunks_total: number
  counts: Record<string, number>
  error: string | null
}
