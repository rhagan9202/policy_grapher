import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut } from '../api/types'

const listDocuments = vi.fn()
vi.mock('../api/client', () => ({
  listDocuments: () => listDocuments(),
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

afterEach(() => listDocuments.mockReset())

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
