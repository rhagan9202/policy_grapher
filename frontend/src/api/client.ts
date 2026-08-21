import type {
  Answer,
  DocumentIn,
  DocumentOut,
  DocumentVersionOut,
  GraphOut,
  IngestResult,
  QueryResult,
  ResetResult,
  ReviewItem,
  TriageOut,
  Verdict,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

// The dev proxy injects the bearer token only for requests carrying this header
// (vite.config.ts, ADR-018). A cross-origin page cannot set it — custom headers
// force a CORS preflight, which `mode: 'no-cors'` forbids — so a drive-by cannot
// borrow our credentials. Removing it here silently breaks every request.
const UI_HEADER = { 'x-policy-grapher-ui': '1' } as const

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...UI_HEADER, ...init?.headers },
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      // Keep the status text when the body is not JSON.
    }
    throw new ApiError(response.status, detail)
  }
  // 204 has no body; json() would throw.
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function getHealth(): Promise<{ status: string }> {
  return request<{ status: string }>('/health')
}

export function ingest(filename: string): Promise<IngestResult> {
  return request<IngestResult>('/ingest', {
    method: 'POST',
    body: JSON.stringify({ filename }),
  })
}

export interface GraphOptions {
  includeExternal?: boolean
  expand?: string
  limit?: number
}

export function getGraph(options: GraphOptions = {}): Promise<GraphOut> {
  const params = new URLSearchParams()
  if (options.includeExternal) params.set('include_external', 'true')
  if (options.expand) params.set('expand', options.expand)
  if (options.limit !== undefined) params.set('limit', String(options.limit))

  const query = params.toString()
  return request<GraphOut>(`/graph${query ? `?${query}` : ''}`)
}

export function listDocuments(): Promise<DocumentOut[]> {
  return request<DocumentOut[]>('/documents')
}

export function getDocument(slug: string): Promise<DocumentOut> {
  return request<DocumentOut>(`/documents/${encodeURIComponent(slug)}`)
}

export function createDocument(document: DocumentIn): Promise<DocumentOut> {
  return request<DocumentOut>('/documents', {
    method: 'POST',
    body: JSON.stringify(document),
  })
}

export function deleteDocument(slug: string): Promise<void> {
  return request<void>(`/documents/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

export function addReference(slug: string, targetSlug: string): Promise<void> {
  return request<void>(
    `/documents/${encodeURIComponent(slug)}/references/${encodeURIComponent(targetSlug)}`,
    { method: 'POST' },
  )
}

export function removeReference(slug: string, targetSlug: string): Promise<void> {
  return request<void>(
    `/documents/${encodeURIComponent(slug)}/references/${encodeURIComponent(targetSlug)}`,
    { method: 'DELETE' },
  )
}

export function reset(): Promise<ResetResult> {
  return request<ResetResult>('/reset', { method: 'POST' })
}

export function runQuery(cypher: string): Promise<QueryResult> {
  return request<QueryResult>('/query', {
    method: 'POST',
    body: JSON.stringify({ cypher }),
  })
}

export function listVersions(slug: string): Promise<DocumentVersionOut[]> {
  return request<DocumentVersionOut[]>(
    `/documents/${encodeURIComponent(slug)}/versions`,
  )
}

export function getReviewQueue(limit?: number): Promise<ReviewItem[]> {
  const query = limit === undefined ? '' : `?limit=${limit}`
  return request<ReviewItem[]>(`/review/queue${query}`)
}

// A write, and therefore dependent on the ADR-018 header that `request` adds.
// Calling fetch directly here would drop it and 401.
export function recordVerdict(
  sourceId: string,
  targetId: string,
  verdict: Verdict,
  rationale = '',
): Promise<Record<string, number>> {
  return request<Record<string, number>>(
    `/review/${encodeURIComponent(sourceId)}/${encodeURIComponent(targetId)}`,
    { method: 'POST', body: JSON.stringify({ verdict, rationale }) },
  )
}

export function getTriage(
  toVersionId: string,
  fromVersionId?: string,
): Promise<TriageOut> {
  const params = new URLSearchParams({ to_version_id: toVersionId })
  if (fromVersionId) params.set('from_version_id', fromVersionId)
  return request<TriageOut>(`/triage?${params.toString()}`)
}

export function ask(question: string): Promise<Answer> {
  return request<Answer>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}
