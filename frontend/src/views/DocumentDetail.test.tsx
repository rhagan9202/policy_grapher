import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const getDocument = vi.fn()
const listVersions = vi.fn()
const listChunks = vi.fn()
vi.mock('../api/client', () => ({
  getDocument: (slug: string) => getDocument(slug),
  listVersions: (slug: string) => listVersions(slug),
  listChunks: (slug: string, versionId?: string) => listChunks(slug, versionId),
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
