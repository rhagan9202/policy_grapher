import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const getDocument = vi.fn()
const listVersions = vi.fn()
const listChunks = vi.fn()
const startRebuild = vi.fn()
const getRebuild = vi.fn()
vi.mock('../api/client', () => ({
  getDocument: (slug: string) => getDocument(slug),
  listVersions: (slug: string) => listVersions(slug),
  listChunks: (slug: string, versionId?: string) => listChunks(slug, versionId),
  startRebuild: (slug: string, versionId: string, candidates: string[]) =>
    startRebuild(slug, versionId, candidates),
  getRebuild: (runId: string) => getRebuild(runId),
  ApiError: class extends Error {},
}))

import DocumentDetail from './DocumentDetail'

const document = {
  slug: 'dodd-5000-01',
  name: 'DoDD 5000.01',
  is_external: false,
  references: ['public-law-116-92'],
  referenced_by: [],
  version_count: 2,
}

const versions = [
  {
    version_id: 'dodd-5000-01@2018-08-31',
    effective_date: '2018-08-31',
    checksum: '65e873',
    source_uri: 'file:///data/samples/500001p_2003.pdf',
    supersedes: null,
  },
  {
    version_id: 'dodd-5000-01@2020-09-09',
    effective_date: '2020-09-09',
    checksum: 'a16e39',
    source_uri: 'file:///data/samples/500001p_2020.pdf',
    supersedes: 'dodd-5000-01@2018-08-31',
  },
]

const chunks = [
  {
    chunk_id: 'c1',
    text: 'The Director shall notify the Comptroller within 24 hours.',
    page: 5,
    section_path: ['ENCLOSURE 1', '1.1'],
    ordinal: 0,
  },
  {
    chunk_id: 'c2',
    text: 'Test and evaluation will be integrated with modeling and simulation.',
    page: 6,
    section_path: ['ENCLOSURE 1', '1.2'],
    ordinal: 1,
  },
]

function renderAt(slug = 'dodd-5000-01') {
  return render(
    <MemoryRouter initialEntries={[`/documents/${slug}`]}>
      <Routes>
        <Route path="/documents/:slug" element={<DocumentDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  getDocument.mockReset()
  listVersions.mockReset()
  listChunks.mockReset()
  startRebuild.mockReset()
  getRebuild.mockReset()
})

// STORY-017, the "corpus management" MVP item. `GET /documents/{slug}/chunks` has
// served ordered text with page and section_path since ADR-012, and `client.ts` had
// no function for the route at all — so nothing in the UI could read a document's
// text.

describe('DocumentDetail', () => {
  it('shows the document it was asked for', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    expect(await screen.findByRole('heading', { name: /DoDD 5000\.01/ })).toBeInTheDocument()
    expect(getDocument).toHaveBeenCalledWith('dodd-5000-01')
  })

  it('renders the extracted text in order, with its page and section', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    const text = await screen.findByRole('article')
    expect(text).toHaveTextContent(/The Director shall notify/)
    expect(text).toHaveTextContent(/ENCLOSURE 1/)
    expect(text).toHaveTextContent(/5/)
  })

  it('reads the newest edition by default and lets another be chosen', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()
    await screen.findByRole('article')

    // Omitted version_id means "newest" at the API, which is the right default.
    expect(listChunks).toHaveBeenCalledWith('dodd-5000-01', undefined)

    await userEvent.selectOptions(
      screen.getByLabelText(/edition/i),
      'dodd-5000-01@2018-08-31',
    )
    expect(listChunks).toHaveBeenLastCalledWith('dodd-5000-01', 'dodd-5000-01@2018-08-31')
  })

  it('says a document has no text rather than rendering an empty page', async () => {
    // The state the sample CSV produces for all 438 of its documents: a manifest
    // records no text (ADR-011). Sprint 3 shipped a defect of exactly this shape.
    getDocument.mockResolvedValue({ ...document, version_count: 0 })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    renderAt()

    expect(await screen.findByText(/no ingested text/i)).toBeInTheDocument()
  })

  it('shows what the document cites', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    renderAt()

    const references = await screen.findByRole('list', { name: /references/i })
    expect(within(references).getByText(/public-law-116-92/)).toBeInTheDocument()
  })

  it('reports a document that is not there instead of rendering blanks', async () => {
    getDocument.mockRejectedValue(new Error('No document with slug "nope"'))
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    renderAt('nope')

    expect(await screen.findByRole('alert')).toHaveTextContent(/No document with slug/)
  })
})

// --- STORY-061: the derived layer can be built from the UI ---------------------
//
// `POST .../rebuild` and `GET /rebuilds/{run_id}` shipped in sprint 4 and
// `api/client.ts` modelled neither, so sprint 4's whole deliverable could only be
// reached with curl. The same class of gap `listChunks` was, one sprint newer.

describe('DocumentDetail — building the derived layer', () => {
  function loaded() {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
  }

  it('queues a rebuild for the edition being read', async () => {
    loaded()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09', candidate_version_ids: [],
    })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09', state: 'started',
      chunks_done: 0, chunks_total: 34, counts: {}, error: null,
    })
    renderAt()
    await screen.findByRole('article')

    await userEvent.selectOptions(screen.getByLabelText(/edition/i), 'dodd-5000-01@2020-09-09')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [])
  })

  it('proposes against the editions the reader chose', async () => {
    loaded()
    startRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'dodd-5000-01@2020-09-09',
      candidate_version_ids: ['dodd-5000-01@2018-08-31'],
    })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 0, chunks_total: 34, counts: {}, error: null,
    })
    renderAt()
    await screen.findByRole('article')

    await userEvent.selectOptions(screen.getByLabelText(/edition/i), 'dodd-5000-01@2020-09-09')
    await userEvent.click(screen.getByRole('checkbox', { name: /2018-08-31/ }))
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(startRebuild).toHaveBeenCalledWith('dodd-5000-01', 'dodd-5000-01@2020-09-09', [
      'dodd-5000-01@2018-08-31',
    ])
  })

  it('reports progress while the run is in flight', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 5, chunks_total: 34, counts: {}, error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/5 of 34/)).toBeInTheDocument()
  })

  it('reports what a finished run produced, including what it rejected', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 121, proposed: 313, chunks_rejected: 1 },
      error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/121/)
    expect(status).toHaveTextContent(/313/)
    // A rejected chunk is silent incompleteness unless the number is shown (ADR-023).
    expect(status).toHaveTextContent(/1 chunk/i)
  })

  it('surfaces a failed run rather than leaving it spinning', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'failed',
      chunks_done: 5, chunks_total: 38, counts: {},
      error: 'model output did not match the obligation schema',
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/did not match/i)
  })
})
