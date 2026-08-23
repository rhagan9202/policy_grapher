import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut } from '../api/types'

const listDocuments = vi.fn()
const createDocument = vi.fn()
const deleteDocument = vi.fn()
const addReference = vi.fn()
const removeReference = vi.fn()
vi.mock('../api/client', () => ({
  listDocuments: () => listDocuments(),
  createDocument: (document: { name: string }) => createDocument(document),
  deleteDocument: (slug: string) => deleteDocument(slug),
  addReference: (slug: string, target: string) => addReference(slug, target),
  removeReference: (slug: string, target: string) => removeReference(slug, target),
  ApiError: class extends Error {},
}))

import DocumentTable from './DocumentTable'

const documents: DocumentOut[] = [
  {
    slug: 'dodd-5000-01',
    name: 'DoDD 5000.01',
    is_external: false,
    references: ['public-law-116-92'],
    referenced_by: [],
    version_count: 0,
  },
  {
    slug: 'dodi-3115-14',
    name: 'DoDI 3115.14',
    is_external: false,
    references: [],
    referenced_by: [],
    version_count: 0,
  },
  {
    slug: 'public-law-116-92',
    name: 'Public Law 116-92',
    is_external: true,
    references: [],
    referenced_by: ['dodd-5000-01'],
    version_count: 0,
  },
]

afterEach(() => {
  listDocuments.mockReset()
  createDocument.mockReset()
  deleteDocument.mockReset()
  addReference.mockReset()
  removeReference.mockReset()
})

describe('DocumentTable', () => {
  it('renders a row per document with its name', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    await waitFor(() => expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument())
    expect(screen.getAllByRole('row')).toHaveLength(documents.length + 1) // + header
  })

  it('counts how many documents cite each one, derived from referenced_by', async () => {
    // ADR-006: a document's standing among others is read off the edges, not a
    // stored label. public-law-116-92 is cited once; dodd-5000-01 by nobody.
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    const cited = await screen.findByRole('row', { name: /^Public Law 116-92/ })
    expect(cited).toHaveTextContent('1')
    const uncited = await screen.findByRole('row', { name: /^DoDD 5000.01/ })
    expect(uncited).toHaveTextContent('0')
  })

  it('still marks which documents are external', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    // Anchored: the DoDD 5000.01 row also names Public Law 116-92, in its
    // References cell. Only the external document's own row starts with it.
    const row = await screen.findByRole('row', { name: /^Public Law 116-92/ })
    expect(row).toHaveTextContent(/external/i)
    expect(row.textContent).not.toMatch(/null/i)
  })

  it('resolves reference slugs to document names', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)

    const row = await screen.findByRole('row', { name: /DoDD 5000.01/ })
    expect(row).toHaveTextContent('Public Law 116-92')
    expect(row.textContent).not.toContain('public-law-116-92')
  })

  it('filters by name as the user types', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'DoDI')

    expect(screen.getByText('DoDI 3115.14')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 5000.01')).not.toBeInTheDocument()
  })

  it('filters case-insensitively', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'public law')

    expect(screen.getByText('Public Law 116-92')).toBeInTheDocument()
  })

  it('says so when a filter matches nothing', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'zzzz')

    expect(screen.getByText(/no documents match/i)).toBeInTheDocument()
  })

  it('surfaces a fetch failure', async () => {
    listDocuments.mockRejectedValue(new Error('backend down'))
    render(<DocumentTable />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })
})

describe('DocumentTable when nothing has been ingested', () => {
  it('says the corpus is empty rather than showing a table of nothing', async () => {
    // ADR-019: "Showing 0 of 0" over empty headers reads as a broken fetch.
    listDocuments.mockResolvedValue([])
    render(<DocumentTable />)

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('does not offer a filter over an empty corpus', async () => {
    listDocuments.mockResolvedValue([])
    render(<DocumentTable />)
    await screen.findByRole('status')

    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
  })
})

// --- STORY-044: corpus editing ------------------------------------------------
//
// createDocument, deleteDocument, addReference and removeReference have been built,
// tested and unreachable since STORY-026. The 2026-08-21 audit counted them among
// nine client functions with no UI caller. These tests are what makes them callable.

describe('DocumentTable — creating a document', () => {
  it('creates a document and shows it without a reload', async () => {
    listDocuments.mockResolvedValue(documents)
    createDocument.mockResolvedValue({
      slug: 'dodi-5000-02',
      name: 'DoDI 5000.02',
      is_external: false,
      references: [],
      referenced_by: [],
      version_count: 0,
    })
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.type(screen.getByLabelText(/name of the document to add/i), 'DoDI 5000.02')
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(createDocument).toHaveBeenCalledWith({ name: 'DoDI 5000.02' })
    expect(await screen.findByRole('cell', { name: 'DoDI 5000.02' })).toBeInTheDocument()
  })

  it('refuses to submit a blank name rather than asking the API to', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(createDocument).not.toHaveBeenCalled()
  })

  it('reports a failed create instead of pretending it worked', async () => {
    listDocuments.mockResolvedValue(documents)
    createDocument.mockRejectedValue(new Error('name already exists'))
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.type(screen.getByLabelText(/name of the document to add/i), 'DoDD 5000.01')
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/name already exists/i)
  })
})

describe('DocumentTable — deleting a document', () => {
  it('asks before deleting, and names what it will delete', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /delete DoDD 5000\.01/i }))

    expect(deleteDocument).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toHaveTextContent(/DoDD 5000\.01/)
  })

  it('deletes on confirmation and drops the row', async () => {
    listDocuments.mockResolvedValue(documents)
    deleteDocument.mockResolvedValue(undefined)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /delete DoDD 5000\.01/i }))
    await userEvent.click(screen.getByRole('button', { name: /^delete$/i }))

    expect(deleteDocument).toHaveBeenCalledWith('dodd-5000-01')
    await waitFor(() =>
      expect(screen.queryByRole('cell', { name: 'DoDD 5000.01' })).not.toBeInTheDocument(),
    )
  })

  it('keeps the row when the delete is cancelled', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /delete DoDD 5000\.01/i }))
    await userEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(deleteDocument).not.toHaveBeenCalled()
    expect(screen.getByRole('cell', { name: 'DoDD 5000.01' })).toBeInTheDocument()
  })
})

describe('DocumentTable — cross-referencing', () => {
  it('adds a reference between two documents', async () => {
    listDocuments.mockResolvedValue(documents)
    addReference.mockResolvedValue(undefined)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /references of DoDI 3115\.14/i }))
    await userEvent.selectOptions(
      screen.getByLabelText(/document DoDI 3115\.14 should reference/i),
      'dodd-5000-01',
    )
    await userEvent.click(screen.getByRole('button', { name: /^add reference$/i }))

    expect(addReference).toHaveBeenCalledWith('dodi-3115-14', 'dodd-5000-01')
  })

  it('does not offer a document a reference to itself', async () => {
    listDocuments.mockResolvedValue(documents)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /references of DoDI 3115\.14/i }))
    const picker = screen.getByLabelText(/document DoDI 3115\.14 should reference/i)

    expect(within(picker).queryByRole('option', { name: 'DoDI 3115.14' })).not.toBeInTheDocument()
  })

  it('removes an existing reference', async () => {
    listDocuments.mockResolvedValue(documents)
    removeReference.mockResolvedValue(undefined)
    render(<DocumentTable />)
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /references of DoDD 5000\.01/i }))
    await userEvent.click(
      screen.getByRole('button', { name: /remove reference to Public Law 116-92/i }),
    )

    expect(removeReference).toHaveBeenCalledWith('dodd-5000-01', 'public-law-116-92')
  })
})
