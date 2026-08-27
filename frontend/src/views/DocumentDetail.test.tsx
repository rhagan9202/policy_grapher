import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const getDocument = vi.fn()
const listVersions = vi.fn()
const listChunks = vi.fn()
const startRebuild = vi.fn()
const getRebuild = vi.fn()
const listDocuments = vi.fn()
const listObligations = vi.fn()
vi.mock('../api/client', () => ({
  getDocument: (slug: string) => getDocument(slug),
  listVersions: (slug: string) => listVersions(slug),
  listChunks: (slug: string, versionId?: string) => listChunks(slug, versionId),
  startRebuild: (slug: string, versionId: string, candidates: string[]) =>
    startRebuild(slug, versionId, candidates),
  getRebuild: (runId: string) => getRebuild(runId),
  listDocuments: () => listDocuments(),
  listObligations: (slug: string, versionId: string) =>
    listObligations(slug, versionId),
  ApiError: class extends Error {},
}))

import DocumentDetail from './DocumentDetail'
import { pollDelayMs, FIRST_POLL_MS, MAX_POLL_MS } from './pollDelay'

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

// Every test renders the whole screen, so the obligations fetch fires in all of
// them. A benign default keeps tests that are about something else from having to
// know this route exists; the ones that are about it override.
//
// These two are cleared rather than reset below, and the difference matters.
// `mockReset` removes the implementation as well as the calls, which leaves a
// window between one test's teardown and the next test's setup where a React
// passive effect that has not flushed yet calls a bare `vi.fn()`, gets
// `undefined`, and throws "Cannot read properties of undefined (reading 'then')"
// inside whichever test happens to be running. That was an intermittent failure
// at roughly one run in eight, and an intermittent failure is worse than a red
// one — it teaches people to re-run rather than to look.
beforeEach(() => {
  listObligations.mockResolvedValue({
    obligations: [],
    total: 0,
    returned: 0,
    truncated: false,
  })
  getRebuild.mockResolvedValue({
    run_id: 'idle',
    version_id: 'idle',
    state: 'finished',
    chunks_done: 0,
    chunks_total: 0,
    counts: {},
    rejections: [],
    extractor_adapter: '',
    embedder_adapter: '',
    error: null,
  })
})

afterEach(() => {
  getDocument.mockReset()
  listVersions.mockReset()
  listChunks.mockReset()
  startRebuild.mockReset()
  getRebuild.mockClear()
  listDocuments.mockReset()
  listObligations.mockClear()
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


// STORY-081. Obligations are the product's central noun and had no screen at all:
// reachable only as a count in a rebuild report, two at a time in Review, or
// quoted in a Triage row. Confirming that a 2026-08-25 rebuild wrote 113 of them
// required `cypher-shell`.

describe('DocumentDetail obligations', () => {
  const threeObligations = {
    obligations: [
      {
        obligation_id: 'ob1',
        statement: 'Components shall apply this issuance.',
        modality: 'SHALL',
        section_path: ['SECTION 1', '1.1'],
        page: 3,
      },
      {
        obligation_id: 'ob2',
        statement: 'Components will record their compliance.',
        modality: 'WILL',
        section_path: ['SECTION 1', '1.1'],
        page: 3,
      },
    ],
    total: 2,
    returned: 2,
    truncated: false,
  }

  it('says how many obligations the edition holds and shows them', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue(threeObligations)

    renderAt()

    expect(
      await screen.findByText(/Components shall apply this issuance\./),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Components will record their compliance\./),
    ).toBeInTheDocument()
    // The section and page are what make a statement checkable against the source.
    expect(screen.getAllByText(/SECTION 1/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/p\. 3/).length).toBeGreaterThan(0)
  })

  it('does not report an unbuilt edition as one that yielded nothing', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      obligations: [],
      total: 0,
      returned: 0,
      truncated: false,
    })

    renderAt()

    // Three of four editions in the live graph on 2026-08-26 were in exactly this
    // state. "None found" and "never built" need opposite actions, and this is
    // STORY-081's AC6 — met once STORY-082 landed the build record that can tell
    // them apart. Before that the copy had to hedge between the two.
    expect(
      await screen.findByText(/no obligations recorded for this edition/i),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/this edition has never been built/i),
    ).toBeInTheDocument()
  })

  it('says so when it shows fewer obligations than the edition holds', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      ...threeObligations,
      total: 604,
      returned: 2,
      truncated: true,
    })

    renderAt()

    expect(await screen.findByText(/604/)).toBeInTheDocument()
    expect(screen.getByText(/showing the first 2/i)).toBeInTheDocument()
  })
})


// STORY-082. Three of four editions in the live graph on 2026-08-26 held chunks
// and zero obligations, with nothing to say whether that meant never-built,
// built-with-null, or a run that died. And the run id lived only in React state,
// so reloading the tab stranded a rebuild that was still going — which the
// eight-hour job timeout set the same day made a real loss rather than a nuisance.

const built = (over: Record<string, unknown> = {}) => ({
  ...versions[1],
  build_state: 'finished',
  build_run_id: 'run-9',
  build_started_at: '2026-08-25T10:00:00+00:00',
  build_changed_at: '2026-08-25T11:00:00+00:00',
  build_extractor_adapter: 'local',
  build_embedder_adapter: 'local',
  build_counts: { chunks_written: 37, obligations_written: 113 },
  build_error: null,
  ...over,
})

describe('DocumentDetail build state', () => {
  it('says an edition has never been built', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([versions[0], { ...versions[1] }])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(
      await screen.findByText(/has never been built/i),
    ).toBeInTheDocument()
  })

  it('names when an edition was built and with which extractor', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([versions[0], built()])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(await screen.findByText(/built/i)).toBeInTheDocument()
    expect(screen.getByText(/local/)).toBeInTheDocument()
  })

  it('explains a build that used no extraction model', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({
        build_extractor_adapter: 'null',
        build_counts: { chunks_written: 41, obligations_written: 0 },
      }),
    ])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    // Not "extraction found nothing": the null adapter writes no obligations by
    // design (ADR-028), and saying otherwise sends a user to debug a document
    // when the answer is a setting.
    expect(
      await screen.findByText(/no extraction model was configured/i),
    ).toBeInTheDocument()
  })

  it('reports a build that failed, and why', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({
        build_state: 'failed',
        build_error: 'JobTimeoutException: Task exceeded maximum timeout value',
        build_counts: {},
      }),
    ])
    listChunks.mockResolvedValue(chunks)

    renderAt()

    expect(await screen.findByText(/last build failed/i)).toBeInTheDocument()
    expect(screen.getByText(/JobTimeoutException/)).toBeInTheDocument()
  })

  it('re-attaches to a rebuild that is still running after a reload', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({ build_state: 'started', build_run_id: 'run-live', build_counts: {} }),
    ])
    listChunks.mockResolvedValue(chunks)
    getRebuild.mockResolvedValue({
      run_id: 'run-live',
      version_id: versions[1].version_id,
      state: 'started',
      chunks_done: 12,
      chunks_total: 37,
      counts: {},
      rejections: [],
      extractor_adapter: 'local',
      embedder_adapter: 'local',
      error: null,
    })

    renderAt()

    // The whole point: no one clicked Build in this session, and the page still
    // finds the run. Before this, the id existed only in the state of the tab
    // that started it.
    expect(await screen.findByText(/12 of 37/i)).toBeInTheDocument()
    expect(getRebuild).toHaveBeenCalledWith('run-live')
  })

  it('does not leave a dead run reading as one still building', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue([
      versions[0],
      built({ build_state: 'started', build_run_id: 'run-gone', build_counts: {} }),
    ])
    listChunks.mockResolvedValue(chunks)
    // The worker died without reporting, so RQ no longer knows the job. The
    // record says "started" and will say so for ever unless the two are
    // reconciled against each other.
    getRebuild.mockRejectedValue(new Error('No such run.'))

    renderAt()

    expect(await screen.findByText(/did not finish/i)).toBeInTheDocument()
  })


  it('does not call an edition unbuilt when it plainly holds obligations', async () => {
    getDocument.mockResolvedValue(document)
    // Exactly the live state on 2026-08-26: dodd-5000-01@2020-09-09 holds 113
    // obligations from a rebuild that predates the build record, so it has none.
    // Saying "never built" over a list of its obligations is a contradiction the
    // screen would put in front of a user on the very first edition they open.
    listVersions.mockResolvedValue([versions[0], { ...versions[1] }])
    listChunks.mockResolvedValue(chunks)
    listObligations.mockResolvedValue({
      obligations: [
        {
          obligation_id: 'ob1',
          statement: 'Components shall apply this issuance.',
          modality: 'SHALL',
          section_path: ['SECTION 1'],
          page: 3,
        },
      ],
      total: 113,
      returned: 1,
      truncated: true,
    })

    renderAt()

    expect(await screen.findByText(/113/)).toBeInTheDocument()
    expect(
      screen.queryByText(/has never been built/i),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/before builds were recorded/i)).toBeInTheDocument()
  })
})


// ADR-030 moved the blast radius from the chunk to the item, and the count is
// the condition attached to that decision. Reporting only `chunks_rejected`
// while listing item drops beside it says "0 chunks rejected" above eight
// entries — which is worse than either number alone.

describe('DocumentDetail rebuild reporting', () => {
  const finishedRun = (counts: Record<string, number>, rejections: unknown[]) => ({
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 38, chunks_total: 38, counts, rejections,
    extractor_adapter: 'local', embedder_adapter: 'local', error: null,
  })

  it('reports dropped items separately from rejected chunks', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finishedRun(
        { chunks_written: 38, obligations_written: 90, chunks_rejected: 1, items_dropped: 8 },
        [{ chunk_id: 'c1', reason: 'modality' }],
      ),
    )

    renderAt()
    await screen.findByRole('button', { name: /build derived layer/i })
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/8 statements dropped/i)).toBeInTheDocument()
    expect(screen.getByText(/1 chunk rejected/i)).toBeInTheDocument()
  })

  it('says nothing about drops when there were none', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finishedRun({ chunks_written: 38, obligations_written: 90, chunks_rejected: 0, items_dropped: 0 }, []),
    )

    renderAt()
    await screen.findByRole('button', { name: /build derived layer/i })
    await userEvent.click(screen.getByRole('button', { name: /build derived layer/i }))

    expect(await screen.findByText(/0 chunks rejected/i)).toBeInTheDocument()
    expect(screen.queryByText(/statements dropped/i)).not.toBeInTheDocument()
  })
})

// STORY-089. Asserting the interval that gets computed, not that a timer was set:
// a test that only checks `setTimeout` was called passes against the flat
// two-second poll this exists to replace.
describe('pollDelayMs', () => {
  it('answers a short run as quickly as the flat poll did', () => {
    expect(pollDelayMs(0)).toBe(FIRST_POLL_MS)
  })

  it('grows between successive polls', () => {
    const delays = [0, 1, 2, 3].map(pollDelayMs)
    for (let i = 1; i < delays.length; i += 1) {
      expect(delays[i]).toBeGreaterThan(delays[i - 1])
    }
  })

  it('settles at a ceiling rather than growing without bound', () => {
    expect(pollDelayMs(50)).toBe(MAX_POLL_MS)
    expect(pollDelayMs(500)).toBe(MAX_POLL_MS)
  })

  it('cuts an eight-hour run from ~14,400 requests to under a thousand', () => {
    // The number that motivated the story, computed rather than asserted from
    // memory: how many polls an 8h run costs at this curve.
    let elapsed = 0
    let polls = 0
    while (elapsed < 8 * 60 * 60 * 1000) {
      elapsed += pollDelayMs(polls)
      polls += 1
    }
    expect(polls).toBeLessThan(1000)
    expect(8 * 60 * 60 * 1000 / FIRST_POLL_MS).toBeGreaterThan(14000)
  })
})

// STORY-076. `UNPROMOTABLE` filtered on approvals, so a stranded rejection was
// counted by nothing — and it is the worse of the two losses, because the
// proposal returns to the queue with no sign it was already refused.

describe('DocumentDetail, stranded rejections', () => {
  const finished = (counts: Record<string, number>) => ({
    run_id: 'r', version_id: versions[1].version_id, state: 'finished',
    chunks_done: 37, chunks_total: 37, counts, rejections: [],
    extractor_adapter: 'local', embedder_adapter: 'local', error: null,
  })

  it('reports a stranded rejection and says what it costs', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({ chunks_written: 37, obligations_written: 56, rejections_stranded: 2 }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    expect(await screen.findByText(/2 recorded rejections/i)).toBeInTheDocument()
    expect(screen.getByText(/refused before/i)).toBeInTheDocument()
  })

  it('says nothing about rejections when none were stranded', async () => {
    getDocument.mockResolvedValue(document)
    listVersions.mockResolvedValue(versions)
    listChunks.mockResolvedValue(chunks)
    startRebuild.mockResolvedValue({ run_id: 'r' })
    getRebuild.mockResolvedValue(
      finished({ chunks_written: 37, obligations_written: 56, rejections_stranded: 0 }),
    )

    renderAt()
    await userEvent.click(
      await screen.findByRole('button', { name: /build derived layer/i }),
    )

    await screen.findByText(/37 chunks written|chunks rejected/i)
    expect(screen.queryByText(/recorded rejection/i)).not.toBeInTheDocument()
  })
})
