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
  /** An ingest of a second edition creates no `:Document` node, so "0 nodes
   *  created" is both true and unreadable. The edition and its chunk count are
   *  what the reader needs in order to do the next thing. */
  version_id: string
  chunks_written: number
}

export type IngestResult = ManifestIngestResult | DocumentIngestResult

/** A file the backend can ingest, as `GET /ingest/sources` reports it. */
export interface SourceFile {
  filename: string
  size_bytes: number
  /** What `POST /ingest` will treat this as — read off the ingester's own
   *  predicate server-side, not guessed from the extension here. */
  kind: string
  /** A `:Source` for this filename already exists. Informational: re-ingesting
   *  is how a second edition arrives, and stays additive (ADR-007). */
  ingested: boolean
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
  /** Editions this document has. Zero for the great majority — an externally
   *  cited document has no ingested text, so it can never be triaged. */
  version_count: number
}

/** One flagged near-duplicate pair, with what a person needs to rule on it. */
export interface DuplicateCandidate {
  names: string[]
  slugs: string[]
  cited_by: number[]
  has_text: boolean[]
  mergeable: boolean
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

  // STORY-082. `build_state` null means no rebuild has ever been recorded for
  // this edition — which is the answer that separates "never built" from "built
  // and found nothing", two readings of an obligation count of zero that need
  // opposite actions.
  build_state?: 'started' | 'finished' | 'failed' | null
  build_run_id?: string | null
  build_started_at?: string | null
  build_changed_at?: string | null
  build_extractor_adapter?: string | null
  build_embedder_adapter?: string | null
  build_counts?: Record<string, number>
  build_error?: string | null
}

/** One obligation as a reader meets it — STORY-081. */
export interface Obligation {
  obligation_id: string
  statement: string
  modality: string
  section_path: string[]
  page: number
}

// Bounded, like GraphOut: `total` is what the edition holds, `returned` what
// came back. STORY-081.
export interface ObligationsOut {
  obligations: Obligation[]
  total: number
  returned: number
  truncated: boolean
}

export interface ObligationCitation {
  obligation_id: string
  statement: string
  modality: string
  document: string
  /** Which edition this clause is in. A proposal often runs between two editions
   *  of one instrument — every one of the 119 in the live queue on 2026-09-09 did
   *  — and without this both sides of the review screen print the same document
   *  name, leaving the reviewer unable to tell which is which. Same reasoning as
   *  `Citation.version_id` on Ask, and it binds harder here: comparing editions
   *  is the whole of what Review does. */
  version_id: string
  section_path: string[]
  page: number
}

/** The queue plus why it is empty when it is — STORY-090. */
export interface ReviewQueue {
  items: ReviewItem[]
  editions_with_obligations: number
  /** Distinct documents holding at least one obligation in any edition. A
   *  proposal runs between two documents now that same-document pairs belong
   *  to the diff, so the queue can only fill once this reaches 2 — necessary
   *  and not sufficient, since two documents sharing no distinctive wording
   *  clear this and still propose nothing. Branch on `< 2`, which is the
   *  direction that holds; reading 2 as "there should be proposals by now"
   *  does not. The old `documents_comparable` counted documents with two
   *  obligation-holding editions — exactly the configuration that can no
   *  longer yield a proposal, so keeping it would keep the false all-clear it
   *  existed to prevent. */
  documents_with_obligations: number
  /** Undecided proposals in the graph, not rows in `items`. The queue is capped
   *  server-side, so the screen read "Proposal 1 of 50" over 119 waiting — and
   *  kept reading it after every verdict, because deciding one refilled the page
   *  from the remainder. This is the number that falls as the backlog clears. */
  pending: number
}

export interface ReviewItem {
  source: ObligationCitation
  target: ObligationCitation
  confidence: number
  rationale: string
  proposer: string
}

export type Verdict = 'approve' | 'reject'

/** What a reviewer may say about two clauses of one instrument.
 *
 *  Not `Verdict`'s vocabulary, deliberately. `approve`/`reject` answers "does our
 *  clause discharge that duty?"; this answers "is the newer clause the older one
 *  reworded?" — a different question, a different canonical node, and a shared
 *  word would let one screen's copy drift into describing the other's. */
export type PairingVerdict = 'paired' | 'distinct'

/** One pair the diff had an opinion about, and the opinion.
 *
 *  `outcome` is the first rule that fired, in the diff's code order —
 *  `auto_paired`, `partner_taken`, `contested`, `below_threshold` — not four
 *  disjoint conditions: `partner_taken` is contained in `contested`, and the
 *  labels record precedence. `taken_by` names zero to two obligations that
 *  already consumed an end of this pair, which is what makes `partner_taken`
 *  the actionable label rather than merely the narrower one. */
export interface PairingCandidate {
  old: ObligationCitation
  new: ObligationCitation
  confidence: number
  rationale: string
  outcome: string
  taken_by: string[]
}

/** A pair a person has already ruled on. Carries ids rather than statements: it
 *  is listed so a verdict stays reversible, and a settled pair is deliberately
 *  not re-recorded as a candidate — a candidate edge re-asking a settled question
 *  would put it straight back in the queue. */
export interface PairingSettled {
  old_id: string
  new_id: string
  verdict: string
  actor: string
}

export interface PairingQueue {
  items: PairingCandidate[]
  settled: PairingSettled[]
  /** Recorded pairings this diff could not apply, because pass 1 matched one of
   *  the clauses — it exists unchanged in both editions, so the "reworded" claim
   *  has nothing to attach to. Counted, never dropped: the decision is still
   *  recorded and the screen has to say it did not take effect. */
  pairings_unapplied: number
  /** Candidates in the graph, not rows in `items`. The queue is capped
   *  server-side, and the review queue read "Proposal 1 of 50" over 119 waiting
   *  because nothing distinguished the page from the backlog. */
  pending: number
}

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
  /**
   * `paired` verdicts the diff behind this request could not apply, because
   * pass 1 had already matched one of the two clauses as persisting unchanged.
   * Required, not optional: the pairing queue carries the same count and the
   * screen reads it, and a field that may be absent is a field a screen can
   * forget. Not a retraction — the decision is still recorded — but it has to
   * be shown, for the reason `unlinked_changes` has to be.
   */
  pairings_unapplied: number
  /**
   * An empty `rows` has three causes, and they are not the same finding:
   * nothing is linked (`unlinked_changes`), nothing changed (`total_changes`),
   * or nothing was ever extracted. Only these two can tell the third from the
   * second, and the default `null` extractor makes the third the common case.
   */
  from_obligations: number
  to_obligations: number
}

export interface Citation {
  document: string
  /** Which edition the passage is in. Retrieval searches every edition a
   *  document has, superseded ones included, so a citation naming only the
   *  document matches a passage in each of them and settles nothing. */
  version_id: string
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
  rejections: { chunk_id: string; reason: string }[]
  /** Which adapters the worker actually used. Empty until a worker picks the
   *  run up. `null` extracts nothing, so a run under it writes chunks and no
   *  obligations — a correct result indistinguishable from a broken one unless
   *  the screen says which it is. */
  extractor_adapter: string
  embedder_adapter: string
  error: string | null
}
