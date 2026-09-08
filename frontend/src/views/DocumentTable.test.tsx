import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentOut } from '../api/types'

const listDocuments = vi.fn()
const createDocument = vi.fn()
const deleteDocument = vi.fn()
const addReference = vi.fn()
const removeReference = vi.fn()
// STORY-031 put the near-duplicate surface on this screen, so the table's tests
// now reach routes they are not about. `listDuplicates` defaults to nothing —
// every test here is about rows, and `Duplicates.test.tsx` is where that section
// is tested — but it is a mock rather than a constant so the one test that *is*
// about what a merge does to the table underneath it can drive it.
const listDuplicates = vi.fn(() => Promise.resolve([] as unknown[]))
const mergeDocuments = vi.fn()
const markNotDuplicates = vi.fn()
vi.mock('../api/client', () => ({
  listDocuments: () => listDocuments(),
  createDocument: (document: { name: string }) => createDocument(document),
  deleteDocument: (slug: string) => deleteDocument(slug),
  addReference: (slug: string, target: string) => addReference(slug, target),
  removeReference: (slug: string, target: string) => removeReference(slug, target),
  listDuplicates: () => listDuplicates(),
  mergeDocuments: (survivor: string, merged: string) =>
    mergeDocuments(survivor, merged),
  markNotDuplicates: (first: string, second: string) =>
    markNotDuplicates(first, second),
  ApiError: class extends Error {},
}))

import DocumentTable, { PAGE_SIZE } from './DocumentTable'

// A row's name links to its detail page (STORY-017), so the table needs router
// context. MemoryRouter rather than a real one: these tests are about the table.
function renderTable() {
  return render(
    <MemoryRouter>
      <DocumentTable />
    </MemoryRouter>,
  )
}

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
  mergeDocuments.mockReset()
  markNotDuplicates.mockReset()
  // Restored rather than reset: every other test in this file renders the
  // duplicates section without caring about it, and a bare `vi.fn()` returns
  // `undefined` where the component expects a promise.
  listDuplicates.mockReset()
  listDuplicates.mockResolvedValue([])
})

describe('DocumentTable', () => {
  it('renders a row per document with its name', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()

    await waitFor(() => expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument())
    expect(screen.getAllByRole('row')).toHaveLength(documents.length + 1) // + header
  })

  it('counts how many documents cite each one, derived from referenced_by', async () => {
    // ADR-006: a document's standing among others is read off the edges, not a
    // stored label. public-law-116-92 is cited once; dodd-5000-01 by nobody.
    listDocuments.mockResolvedValue(documents)
    renderTable()

    const cited = await screen.findByRole('row', { name: /^Public Law 116-92/ })
    expect(cited).toHaveTextContent('1')
    const uncited = await screen.findByRole('row', { name: /^DoDD 5000.01/ })
    expect(uncited).toHaveTextContent('0')
  })

  it('still marks which documents are external', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()

    // Anchored: the DoDD 5000.01 row also names Public Law 116-92, in its
    // References cell. Only the external document's own row starts with it.
    const row = await screen.findByRole('row', { name: /^Public Law 116-92/ })
    expect(row).toHaveTextContent(/external/i)
    expect(row.textContent).not.toMatch(/null/i)
  })

  it('resolves reference slugs to document names', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()

    const row = await screen.findByRole('row', { name: /DoDD 5000.01/ })
    expect(row).toHaveTextContent('Public Law 116-92')
    expect(row.textContent).not.toContain('public-law-116-92')
  })

  it('filters by name as the user types', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'DoDI')

    expect(screen.getByText('DoDI 3115.14')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 5000.01')).not.toBeInTheDocument()
  })

  it('filters case-insensitively', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'public law')

    expect(screen.getByText('Public Law 116-92')).toBeInTheDocument()
  })

  it('says so when a filter matches nothing', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await waitFor(() => screen.getByText('DoDD 5000.01'))

    await userEvent.type(screen.getByRole('searchbox'), 'zzzz')

    // STORY-014 reworded this to name the term searched for, because "no
    // documents match that filter" left a reader unable to tell a mistyped
    // search from an empty corpus.
    expect(screen.getByText(/no document matches/i)).toBeInTheDocument()
    expect(screen.getByText(/zzzz/)).toBeInTheDocument()
  })

  it('surfaces a fetch failure', async () => {
    listDocuments.mockRejectedValue(new Error('backend down'))
    renderTable()

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })

  it('says which documents have ingested text', async () => {
    // 439 rows look identical, and only two or three have an edition behind
    // them. version_count has been in the payload since STORY-040 and the table
    // has never shown it.
    listDocuments.mockResolvedValue([
      { slug: 'a', name: 'DoDD 5000.01', is_external: false, references: [], referenced_by: [], version_count: 2 },
      { slug: 'b', name: 'DoDD 9999.99', is_external: true, references: [], referenced_by: [], version_count: 0 },
    ])
    renderTable()
    await screen.findByRole('table')

    const withText = screen.getByRole('row', { name: /DoDD 5000\.01/ })
    expect(within(withText).getByText('2')).toBeInTheDocument()
  })

  it('can show only the documents that have text', async () => {
    listDocuments.mockResolvedValue([
      { slug: 'a', name: 'DoDD 5000.01', is_external: false, references: [], referenced_by: [], version_count: 2 },
      { slug: 'b', name: 'DoDD 9999.99', is_external: true, references: [], referenced_by: [], version_count: 0 },
    ])
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('checkbox', { name: /only documents with text/i }))

    expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 9999.99')).not.toBeInTheDocument()
  })

  it('renders a page of rows and says which page it is', async () => {
    listDocuments.mockResolvedValue(
      Array.from({ length: 250 }, (_, i) => ({
        slug: `d-${i}`, name: `Document ${i}`, is_external: false,
        references: [], referenced_by: [], version_count: 0,
      })),
    )
    renderTable()
    await screen.findByRole('table')

    expect(screen.getAllByRole('row').length).toBe(PAGE_SIZE + 1) // + header
    expect(screen.getByText(/showing 1–200 of 250/i)).toBeInTheDocument()
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument()
  })

  it('offers no paging when everything fits on one page', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await screen.findByRole('table')

    expect(screen.queryByRole('button', { name: /next page/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/page 1 of/i)).not.toBeInTheDocument()
  })
})

// Found in the sprint-12 walkthrough. The table rendered the first 200 rows and
// said "Filter to narrow the list and see the rest" — which, over a 448-document
// corpus sorted by name, meant everything after roughly "M" was unreachable
// unless you could already guess what you were looking for. The cap borrowed the
// graph's cap-and-say-so idiom (STORY-015), but the graph is a picture that gets
// unreadable past a few hundred nodes and a table is a list that does not.
describe('DocumentTable paging', () => {
  const many = Array.from({ length: 250 }, (_, i) => ({
    slug: `d-${String(i).padStart(3, '0')}`,
    name: `Document ${String(i).padStart(3, '0')}`,
    is_external: false,
    references: [],
    referenced_by: [],
    version_count: 0,
  }))

  it('reaches the rows past the first page', async () => {
    listDocuments.mockResolvedValue(many)
    renderTable()
    await screen.findByRole('table')

    expect(screen.getByText('Document 000')).toBeInTheDocument()
    expect(screen.queryByText('Document 249')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /next page/i }))

    expect(screen.getByText('Document 249')).toBeInTheDocument()
    expect(screen.queryByText('Document 000')).not.toBeInTheDocument()
    expect(screen.getByText(/showing 201–250 of 250/i)).toBeInTheDocument()
  })

  it('goes back, and will not step off either end', async () => {
    listDocuments.mockResolvedValue(many)
    renderTable()
    await screen.findByRole('table')

    expect(screen.getByRole('button', { name: /previous page/i })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /next page/i }))
    expect(screen.getByRole('button', { name: /next page/i })).toBeDisabled()

    await userEvent.click(screen.getByRole('button', { name: /previous page/i }))
    expect(screen.getByText('Document 000')).toBeInTheDocument()
  })

  it('returns to the first page when the filter changes under it', async () => {
    // Otherwise a filter applied while on page 2 lands on a page that no longer
    // exists, and the table renders empty over a non-zero count — the blank that
    // reads as broken (ADR-019).
    listDocuments.mockResolvedValue(many)
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /next page/i }))
    await userEvent.type(screen.getByRole('searchbox'), 'Document 01')

    expect(screen.getByText('Document 010')).toBeInTheDocument()
    expect(screen.queryByText(/no document matches/i)).not.toBeInTheDocument()
  })
})

// The table arrived in whatever order the API returned, which is by name — so
// "which documents are cited most" and "which have text" could be read off the
// columns but not ordered by them, over 448 rows.
describe('DocumentTable sorting', () => {
  const mixed = [
    { slug: 'c', name: 'Charlie', is_external: false, references: [], referenced_by: ['x'], version_count: 0 },
    { slug: 'a', name: 'Alpha', is_external: false, references: [], referenced_by: ['x', 'y', 'z'], version_count: 2 },
    { slug: 'b', name: 'Bravo', is_external: false, references: [], referenced_by: [], version_count: 1 },
  ]

  const namesInOrder = () =>
    screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent)

  it('starts in name order', async () => {
    listDocuments.mockResolvedValue(mixed)
    renderTable()
    await screen.findByRole('table')

    expect(namesInOrder()).toEqual(['Alpha', 'Bravo', 'Charlie'])
  })

  it('sorts by how often a document is cited, most first', async () => {
    listDocuments.mockResolvedValue(mixed)
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /sort by cited by/i }))

    // Descending first for a count: "which is cited most" is the question a
    // reader has when they click it, and ascending answers "which is cited least".
    expect(namesInOrder()).toEqual(['Alpha', 'Charlie', 'Bravo'])
  })

  it('reverses when the same column is chosen again, and says which way it is sorted', async () => {
    listDocuments.mockResolvedValue(mixed)
    renderTable()
    await screen.findByRole('table')

    const citedBy = screen.getByRole('button', { name: /sort by cited by/i })
    await userEvent.click(citedBy)
    await userEvent.click(citedBy)

    expect(namesInOrder()).toEqual(['Bravo', 'Charlie', 'Alpha'])
    expect(screen.getByRole('columnheader', { name: /cited by/i })).toHaveAttribute(
      'aria-sort',
      'ascending',
    )
  })
})

// The duplicates section led the screen: on a 1024×768 display it took the top
// ~450px and the first document row sat below the fold. Two flagged pairs out of
// 438 documents were given more room than the corpus. It keeps its prominence
// through a line above the table rather than the whole panel.
describe('DocumentTable and the duplicates panel', () => {
  const pair = [
    {
      names: ['Military Standard 882E', 'Military-Standard 882E'],
      slugs: ['military-standard-882e-511614ad', 'military-standard-882e'],
      cited_by: [1, 1],
      has_text: [false, false],
      mergeable: true,
    },
  ]

  it('puts the panel after the table', async () => {
    listDocuments.mockResolvedValue(documents)
    listDuplicates.mockResolvedValue(pair)
    renderTable()

    const table = await screen.findByRole('table')
    const panel = await screen.findByRole('heading', { name: /possible duplicates/i })

    expect(
      table.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
  })

  it('says above the table that a pair is waiting, and links down to it', async () => {
    listDocuments.mockResolvedValue(documents)
    listDuplicates.mockResolvedValue(pair)
    renderTable()

    const table = await screen.findByRole('table')
    const notice = await screen.findByRole('link', { name: /near-duplicate name/i })

    expect(notice).toHaveAttribute('href', '#duplicates')
    expect(
      table.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_PRECEDING,
    ).toBeTruthy()
  })

  it('says nothing above the table when no pair is waiting', async () => {
    listDocuments.mockResolvedValue(documents)
    listDuplicates.mockResolvedValue([])
    renderTable()
    await screen.findByRole('table')

    await waitFor(() =>
      expect(
        screen.queryByRole('link', { name: /near-duplicate name/i }),
      ).not.toBeInTheDocument(),
    )
  })
})

describe('DocumentTable when nothing has been ingested', () => {
  it('says the corpus is empty rather than showing a table of nothing', async () => {
    // ADR-019: "Showing 0 of 0" over empty headers reads as a broken fetch.
    listDocuments.mockResolvedValue([])
    renderTable()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('does not offer a filter over an empty corpus', async () => {
    listDocuments.mockResolvedValue([])
    renderTable()
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
    renderTable()
    await screen.findByRole('table')

    await userEvent.type(screen.getByLabelText(/name of the document to add/i), 'DoDI 5000.02')
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(createDocument).toHaveBeenCalledWith({ name: 'DoDI 5000.02' })
    expect(await screen.findByRole('cell', { name: 'DoDI 5000.02' })).toBeInTheDocument()
  })

  it('refuses to submit a blank name rather than asking the API to', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(createDocument).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/give the document a name/i)
  })

  it('does not answer a blank submit with the previous attempt\'s error', async () => {
    // The bare `return` on a blank name left whatever error was already on screen
    // standing, so pressing Add on an empty box after a name collision explained a
    // collision the reader had not just caused.
    listDocuments.mockResolvedValue(documents)
    createDocument.mockRejectedValue(new Error("A document named 'DoDD 5000.01' already exists."))
    renderTable()
    await screen.findByRole('table')

    const field = screen.getByLabelText(/name of the document to add/i)
    await userEvent.type(field, 'DoDD 5000.01')
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/already exists/i)

    await userEvent.clear(field)
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/give the document a name/i)
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
  })

  it('reports a failed create instead of pretending it worked', async () => {
    listDocuments.mockResolvedValue(documents)
    createDocument.mockRejectedValue(new Error('name already exists'))
    renderTable()
    await screen.findByRole('table')

    await userEvent.type(screen.getByLabelText(/name of the document to add/i), 'DoDD 5000.01')
    await userEvent.click(screen.getByRole('button', { name: /add document/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/name already exists/i)
  })
})

describe('DocumentTable — deleting a document', () => {
  it('asks before deleting, and names what it will delete', async () => {
    listDocuments.mockResolvedValue(documents)
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /delete DoDD 5000\.01/i }))

    expect(deleteDocument).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toHaveTextContent(/DoDD 5000\.01/)
  })

  it('deletes on confirmation and drops the row', async () => {
    listDocuments.mockResolvedValue(documents)
    deleteDocument.mockResolvedValue(undefined)
    renderTable()
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
    renderTable()
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
    renderTable()
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
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /references of DoDI 3115\.14/i }))
    const picker = screen.getByLabelText(/document DoDI 3115\.14 should reference/i)

    expect(within(picker).queryByRole('option', { name: 'DoDI 3115.14' })).not.toBeInTheDocument()
  })

  it('removes an existing reference', async () => {
    listDocuments.mockResolvedValue(documents)
    removeReference.mockResolvedValue(undefined)
    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /references of DoDD 5000\.01/i }))
    await userEvent.click(
      screen.getByRole('button', { name: /remove reference to Public Law 116-92/i }),
    )

    expect(removeReference).toHaveBeenCalledWith('dodd-5000-01', 'public-law-116-92')
  })
})

// STORY-014. STORY-010's filter matched `name` only. The MVP bar says "name or
// ID", and the ID is the slug — the thing that appears in every citation this
// product prints, so a reader who has seen a citation has seen one.

describe('DocumentTable, searching by ID', () => {
  it('finds a document by its slug, not only its name', async () => {
    listDocuments.mockResolvedValue([
      { slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
        references: [], referenced_by: [], version_count: 2 },
      { slug: 'dodm-8180-01', name: 'DoDM 8180.01', is_external: false,
        references: [], referenced_by: [], version_count: 1 },
    ])

    render(
      <MemoryRouter initialEntries={['/documents?q=dodm-8180']}>
        <DocumentTable />
      </MemoryRouter>,
    )

    expect(await screen.findByText('DoDM 8180.01')).toBeInTheDocument()
    expect(screen.queryByText('DoDD 5000.01')).not.toBeInTheDocument()
  })

  it('says what it searched for when nothing matches', async () => {
    listDocuments.mockResolvedValue([
      { slug: 'dodd-5000-01', name: 'DoDD 5000.01', is_external: false,
        references: [], referenced_by: [], version_count: 2 },
    ])

    render(
      <MemoryRouter initialEntries={['/documents?q=nothing-like-this']}>
        <DocumentTable />
      </MemoryRouter>,
    )

    // An empty table is the blank-that-reads-as-broken ADR-019 forbids.
    expect(await screen.findByText(/nothing-like-this/)).toBeInTheDocument()
  })
})

// Found in the sprint-12 walkthrough, driving the real stack. `Duplicates` sits
// inside this table and reloads only its own list after a merge, so the table
// underneath went on rendering what it fetched on mount: with the corpus at 437
// documents the screen said 438, and both halves of the merged pair stayed in the
// table — each with a working-looking name link, References button and Delete
// button, for a document the graph no longer holds. Following the link answers
// 404 and the screen reports it as a failure to load, which is a lie about which
// thing is broken.
//
// A refetch here rather than a local edit, unlike the row actions above: the
// merge is performed by a sibling and its response says how many relationships
// moved, not which document ceased to exist. A merge is also a rare, deliberate
// act, so the cost the comment on `run` weighs against a refetch is not paid on
// every keystroke.
describe('DocumentTable when a duplicate is merged', () => {
  const pair = [
    {
      names: ['Military Standard 882E', 'Military-Standard 882E'],
      slugs: ['military-standard-882e-511614ad', 'military-standard-882e'],
      cited_by: [1, 1],
      has_text: [false, false],
      mergeable: true,
    },
  ]

  const both: DocumentOut[] = [
    {
      slug: 'military-standard-882e-511614ad',
      name: 'Military Standard 882E',
      is_external: true,
      references: [],
      referenced_by: [],
      version_count: 0,
    },
    {
      slug: 'military-standard-882e',
      name: 'Military-Standard 882E',
      is_external: true,
      references: [],
      referenced_by: [],
      version_count: 0,
    },
  ]

  it('drops the merged-away document from the table', async () => {
    listDocuments.mockResolvedValueOnce(both).mockResolvedValue([both[0]])
    listDuplicates.mockResolvedValueOnce(pair).mockResolvedValue([])
    mergeDocuments.mockResolvedValue({ applied: 1 })

    renderTable()
    const table = await screen.findByRole('table')
    expect(await within(table).findByText('Military-Standard 882E')).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: /keep .Military Standard 882E./i }),
    )

    await waitFor(() =>
      expect(within(table).queryByText('Military-Standard 882E')).not.toBeInTheDocument(),
    )
    expect(within(table).getByText('Military Standard 882E')).toBeInTheDocument()
  })

  it('leaves the table alone when a pair is ruled not duplicates', async () => {
    listDocuments.mockResolvedValue(both)
    listDuplicates.mockResolvedValueOnce(pair).mockResolvedValue([])
    markNotDuplicates.mockResolvedValue(undefined)

    renderTable()
    await screen.findByRole('table')

    await userEvent.click(screen.getByRole('button', { name: /these are different/i }))

    // Nothing ceased to exist, so nothing is refetched — the decision is recorded
    // against the pair and both documents are still in the corpus.
    await waitFor(() => expect(markNotDuplicates).toHaveBeenCalled())
    expect(listDocuments).toHaveBeenCalledTimes(1)
  })
})
