import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getGraph, getHealth, ingest } from './client'

function mockJson(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
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
