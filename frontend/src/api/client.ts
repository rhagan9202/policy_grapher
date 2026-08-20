import type {
  DocumentIn,
  DocumentOut,
  GraphOut,
  IngestResult,
  QueryResult,
  ResetResult,
} from './types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
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
