import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  addReference,
  createDocument,
  deleteDocument,
  getDocument,
  getGraph,
  getHealth,
  ask,
  getTriage,
  ingest,
  listDocuments,
  recordVerdict,
  runQuery,
} from './client'

function mockJson(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  })
}

function mockNoContent() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 204,
    json: async () => {
      throw new Error('204 responses have no body')
    },
    text: async () => '',
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the dev-proxy header', () => {
  it('is sent on reads', async () => {
    const fetchMock = mockJson({ nodes: [], edges: [], total_nodes: 0, returned_nodes: 0, truncated: false })
    vi.stubGlobal('fetch', fetchMock)

    await getGraph()

    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers['x-policy-grapher-ui']).toBe('1')
  })

  it('is sent on writes, which is the whole reason the proxy takes them', async () => {
    const fetchMock = mockJson({ slug: 'x', name: 'X', is_external: false, references: [], referenced_by: [] }, 201)
    vi.stubGlobal('fetch', fetchMock)

    await createDocument({ name: 'X' })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('POST')
    expect(init.headers['x-policy-grapher-ui']).toBe('1')
  })

  it('does not lose Content-Type when a caller supplies its own headers', async () => {
    const fetchMock = mockJson({ nodes: [], edges: [], total_nodes: 0, returned_nodes: 0, truncated: false })
    vi.stubGlobal('fetch', fetchMock)

    await getGraph()

    const headers = fetchMock.mock.calls[0][1].headers
    expect(headers['Content-Type']).toBe('application/json')
  })
})

describe('getGraph', () => {
  it('requests the default corpus view with no query string', async () => {
    const fetchMock = mockJson({
      nodes: [], edges: [], total_nodes: 23, returned_nodes: 23, truncated: false,
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await getGraph()

    expect(fetchMock).toHaveBeenCalledWith('/api/graph', expect.anything())
    expect(result.total_nodes).toBe(23)
  })

  it('serialises include_external, expand, and limit', async () => {
    const fetchMock = mockJson({
      nodes: [], edges: [], total_nodes: 438, returned_nodes: 300, truncated: true,
    })
    vi.stubGlobal('fetch', fetchMock)

    await getGraph({ includeExternal: true, expand: 'dodd-5000-01', limit: 300 })

    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('include_external=true')
    expect(url).toContain('expand=dodd-5000-01')
    expect(url).toContain('limit=300')
  })

  it('throws ApiError on a non-2xx response', async () => {
    vi.stubGlobal('fetch', mockJson({ detail: 'No document' }, 404))
    await expect(getGraph({ expand: 'nope' })).rejects.toBeInstanceOf(ApiError)
  })
})

describe('ingest', () => {
  it('posts the filename', async () => {
    const fetchMock = mockJson({
      nodes_created: 438,
      relationships_created: 672,
      self_references_skipped: 4,
      suspected_duplicates: [],
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await ingest('sample.csv')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/ingest')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ filename: 'sample.csv' })
    expect(result.nodes_created).toBe(438)
  })
})

describe('getHealth', () => {
  it('returns the status payload', async () => {
    vi.stubGlobal('fetch', mockJson({ status: 'ok' }))
    expect(await getHealth()).toEqual({ status: 'ok' })
  })
})

describe('documents', () => {
  it('lists documents', async () => {
    const fetchMock = mockJson([])
    vi.stubGlobal('fetch', fetchMock)

    await listDocuments()

    expect(fetchMock).toHaveBeenCalledWith('/api/documents', expect.anything())
  })

  it('reads one by slug', async () => {
    const fetchMock = mockJson({ slug: 'dodd-5000-01' })
    vi.stubGlobal('fetch', fetchMock)

    await getDocument('dodd-5000-01')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/dodd-5000-01')
  })

  it('posts a new document', async () => {
    const fetchMock = mockJson({ slug: 'dodd-9999-01' }, 201)
    vi.stubGlobal('fetch', fetchMock)

    await createDocument({ name: 'DoDD 9999.01' })

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ name: 'DoDD 9999.01' })
  })

  it('resolves rather than throwing on a 204', async () => {
    // request() calls response.json() unconditionally today, which throws on an
    // empty body — five of the nine new endpoints return 204.
    vi.stubGlobal('fetch', mockNoContent())

    await expect(deleteDocument('dodd-5000-01')).resolves.toBeUndefined()
  })

  it('adds a reference at the nested path', async () => {
    const fetchMock = mockNoContent()
    vi.stubGlobal('fetch', fetchMock)

    await addReference('dodd-5000-01', 'dodi-3115-14')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/dodd-5000-01/references/dodi-3115-14')
    expect(init.method).toBe('POST')
  })
})

describe('runQuery', () => {
  it('posts the cypher string', async () => {
    const fetchMock = mockJson({ rows: [], returned_rows: 0, truncated: false })
    vi.stubGlobal('fetch', fetchMock)

    const result = await runQuery('MATCH (d:Document) RETURN count(d) AS total')

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      cypher: 'MATCH (d:Document) RETURN count(d) AS total',
    })
    expect(result.rows).toEqual([])
  })
})

describe('the phase-6 endpoints', () => {
  it('sends the dev-proxy header on a review verdict, which is a write', async () => {
    // ADR-018: the proxy injects the bearer token only for requests carrying it.
    // A verdict posted without it 401s, and the audit record is never written.
    const fetchMock = mockJson({ promoted: 1, suppressed: 0, unpromotable: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await recordVerdict('src-id', 'tgt-id', 'approve', 'Discharges the duty.')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers).toMatchObject({ 'x-policy-grapher-ui': '1' })
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      verdict: 'approve',
      rationale: 'Discharges the duty.',
    })
  })

  it('sends the dev-proxy header when asking a question', async () => {
    const fetchMock = mockJson({ answer: 'x', citations: [], template_used: 'x' })
    vi.stubGlobal('fetch', fetchMock)

    await ask('what obliges the Director?')

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers).toMatchObject({ 'x-policy-grapher-ui': '1' })
  })

  it('escapes obligation ids into the verdict path', async () => {
    const fetchMock = mockJson({})
    vi.stubGlobal('fetch', fetchMock)

    await recordVerdict('a/b', 'c d', 'reject')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/review/a%2Fb/c%20d')
  })

  it('omits from_version_id when it was not chosen', async () => {
    const fetchMock = mockJson({ rows: [], total_changes: 0, unlinked_changes: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await getTriage('v2')

    expect(fetchMock.mock.calls[0][0]).toBe('/api/triage?to_version_id=v2')
  })

  it('passes from_version_id when it was', async () => {
    const fetchMock = mockJson({ rows: [], total_changes: 0, unlinked_changes: 0 })
    vi.stubGlobal('fetch', fetchMock)

    await getTriage('v2', 'v1')

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/triage?to_version_id=v2&from_version_id=v1',
    )
  })
})
