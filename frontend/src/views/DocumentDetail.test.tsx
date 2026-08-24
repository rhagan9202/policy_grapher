import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const getDocument = vi.fn()
const listVersions = vi.fn()
const listChunks = vi.fn()
const startRebuild = vi.fn()
const getRebuild = vi.fn()
const listDocuments = vi.fn()
vi.mock('../api/client', () => ({
  getDocument: (slug: string) => getDocument(slug),
  listVersions: (slug: string) => listVersions(slug),
  listChunks: (slug: string, versionId?: string) => listChunks(slug, versionId),
  startRebuild: (slug: string, versionId: string, candidates: string[]) =>
    startRebuild(slug, versionId, candidates),
  getRebuild: (runId: string) => getRebuild(runId),
  listDocuments: () => listDocuments(),
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
  listDocuments.mockReset()
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

  it('names and links the documents this one cites', async () => {
    // The detail page listed raw slugs, unlinked, while the table two clicks
    // away resolved the same slugs to names and linked every row.
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])
    listDocuments.mockResolvedValue([
      { slug: 'dodd-1322-18', name: 'DoDD 1322.18', is_external: false, references: [], referenced_by: [], version_count: 0 },
    ])
    renderAt()

    const link = await screen.findByRole('link', { name: 'DoDD 1322.18' })
    expect(link).toHaveAttribute('href', '/documents/dodd-1322-18')
  })

  it('falls back to the slug when the name is not known yet, surviving a genuine lookup failure', async () => {
    getDocument.mockResolvedValue({
      slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
      references: ['dodd-1322-18'], referenced_by: [], version_count: 1,
    })
    listVersions.mockResolvedValue([])
    listChunks.mockResolvedValue([])

    // A promise this test controls, so the final assertion cannot pass on the
    // pre-settle default state alone (the empty `namesBySlug` a component with
    // no lookup at all, or one whose `.catch` was deleted, would also show).
    let rejectLookup!: (error: Error) => void
    const lookup = new Promise<never>((_, reject) => {
      rejectLookup = reject
    })
    listDocuments.mockReturnValue(lookup)
    renderAt()

    await screen.findByRole('link', { name: 'dodd-1322-18' })
    // The lookup must actually have been attempted: a deleted effect renders the
    // same slug fallback without ever calling listDocuments.
    expect(listDocuments).toHaveBeenCalled()

    rejectLookup(new Error('offline'))
    await lookup.catch(() => {})

    // A failed name lookup must not blank the references list — the slug is
    // still a working link — and the rejection must not surface as an error
    // banner, which is what an unhandled `.catch` would do.
    expect(await screen.findByRole('link', { name: 'dodd-1322-18' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
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
      chunks_done: 0, chunks_total: 34, counts: {}, rejections: [], error: null,
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
      chunks_done: 0, chunks_total: 34, counts: {}, rejections: [], error: null,
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
      chunks_done: 5, chunks_total: 34, counts: {}, rejections: [], error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/5 of 34/)).toBeInTheDocument()
  })

  it('says a run extracted nothing because it was configured to, not because it broke', async () => {
    // The default EXTRACTOR_ADAPTER is null. A rebuild under it finishes
    // cleanly with every chunk written and zero obligations — a correct result
    // that reads exactly like a broken pipeline, and the reader cannot see the
    // worker's configuration from this screen.
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 0, proposed: 0, chunks_rejected: 0 },
      rejections: [], extractor_adapter: 'null', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/null.*extractor/i)
    expect(status).toHaveTextContent(/review and triage stay empty/i)
  })

  it('does not blame the null extractor when a real one ran', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265, chunks_rejected: 0 },
      rejections: [], extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).not.toHaveTextContent(/null.*extractor/i)
  })

  it('reports what a finished run produced, including what it rejected', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 121, proposed: 313, chunks_rejected: 1 },
      rejections: [{ chunk_id: 'c9', reason: 'modality: Input should be SHALL, MUST, WILL, SHOULD or MAY' }],
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
      chunks_done: 5, chunks_total: 38, counts: {}, rejections: [],
      error: 'model output did not match the obligation schema',
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/did not match/i)
  })

  it('says a run is queued rather than reporting "0 of 0"', async () => {
    // Found by the sprint 5 walkthrough. A run reports chunks_total 0 until the
    // worker picks it up, and "Building: 0 of 0 chunks" reads as a rebuild that
    // found nothing to do rather than one that has not started.
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'started',
      chunks_done: 0, chunks_total: 0, counts: {}, rejections: [], error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/queued/i)
    expect(status).not.toHaveTextContent(/0 of 0/)
  })

  it('says why chunks were rejected, not only how many', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 0, chunks_rejected: 2 },
      rejections: [
        { chunk_id: 'c9', reason: 'modality: Input should be SHALL, MUST, WILL, SHOULD or MAY' },
      ],
      error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/2 chunks rejected/i)
    expect(status).toHaveTextContent(/Input should be SHALL/)
  })

  it('says when a recorded approval could not be replayed', async () => {
    // replay_decisions has returned this count since it was written and nothing
    // has ever shown it. An approval that stopped being represented in the graph
    // is exactly the case a healthy-looking rebuild must not hide (ADR-027).
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 2, unpromotable: 3 },
      rejections: [], extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).toHaveTextContent(/3 recorded approvals could not be replayed/i)
    expect(status).toHaveTextContent(/2 .*carried across/i)
  })

  it('stays quiet about decisions when there were none to carry or lose', async () => {
    loaded()
    startRebuild.mockResolvedValue({ run_id: 'r1', version_id: 'v', candidate_version_ids: [] })
    getRebuild.mockResolvedValue({
      run_id: 'r1', version_id: 'v', state: 'finished',
      chunks_done: 34, chunks_total: 34,
      counts: { chunks_written: 34, obligations_written: 115, proposed: 265,
                chunks_rejected: 0, decisions_repointed: 0, unpromotable: 0 },
      rejections: [], extractor_adapter: 'local', embedder_adapter: 'null', error: null,
    })
    renderAt()
    await screen.findByRole('article')
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    const status = await screen.findByRole('status')
    expect(status).not.toHaveTextContent(/could not be replayed/i)
    expect(status).not.toHaveTextContent(/carried across/i)
  })
})
