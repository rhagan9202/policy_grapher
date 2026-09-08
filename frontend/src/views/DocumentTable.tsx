import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Duplicates from './Duplicates'
import {
  addReference,
  createDocument,
  deleteDocument,
  listDocuments,
  removeReference,
} from '../api/client'
import EmptyState from './EmptyState'
import type { DocumentOut } from '../api/types'

function messageOf(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback
}

/** Rows per page.
 *
 *  This was a hard render cap borrowed from the graph (STORY-015): draw the first
 *  200, say so, and tell the reader to filter. The idiom does not transfer. A
 *  graph past a few hundred nodes is an unreadable picture and capping it is the
 *  kindest thing to do; a table is a list, and capping one makes every row after
 *  the two-hundredth unreachable to anyone who cannot already guess its name. In
 *  a 448-document corpus sorted by name that was everything past roughly "M".
 *
 *  The number is unchanged — 200 rows is still as many as a person can use at
 *  once, and mounting 448 rows of nested controls is still worth avoiding. What
 *  changed is that there is now a second page. */
export const PAGE_SIZE = 200

/** Which column the table is ordered by. `name` is what the API already returns,
 *  so it is the default and costs no reordering. */
type SortKey = 'name' | 'cited' | 'editions'

const SORT_LABELS: Record<SortKey, string> = {
  name: 'Name',
  cited: 'Cited by',
  editions: 'Editions',
}

/** Counts descend on first click and names ascend, because that is the question
 *  each column is clicked to answer: "which is cited most", "which is first
 *  alphabetically". */
const FIRST_DIRECTION: Record<SortKey, 'asc' | 'desc'> = {
  name: 'asc',
  cited: 'desc',
  editions: 'desc',
}

function sortValue(document: DocumentOut, key: SortKey): string | number {
  if (key === 'cited') return document.referenced_by.length
  if (key === 'editions') return document.version_count
  return document.name.toLowerCase()
}

export default function DocumentTable() {
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // STORY-014. The URL *is* the filter rather than seeding a copy of it: a search
  // made anywhere else arrives here already applied, a searched URL is shareable
  // and survives a reload, and there is no second source of truth to synchronise —
  // which is what the cascading-render lint rule objects to, and rightly.
  // `replace` so typing does not push a history entry per keystroke.
  const [params, setParams] = useSearchParams()
  const filter = params.get('q') ?? ''
  const setFilter = (value: string) =>
    setParams(value ? { q: value } : {}, { replace: true })
  const [withText, setWithText] = useState(false)

  const [page, setPage] = useState(0)
  const [sortKey, setSortKey] = useState<SortKey>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  // How many near-duplicate pairs are still unruled, reported up by the panel
  // below the table so the line above it can say a decision is waiting without
  // fetching the same list twice.
  const [duplicatePairs, setDuplicatePairs] = useState(0)

  // Corpus editing (STORY-044). The five client functions behind these three flows
  // have been built and unreachable since STORY-026.
  const [newName, setNewName] = useState('')
  const [editError, setEditError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // The slug awaiting a delete confirmation, and the slug whose references are open.
  // Both are single-valued: two open confirmations is a way to delete the wrong one.
  const [confirming, setConfirming] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [referenceTarget, setReferenceTarget] = useState('')

  // Named rather than inlined in the effect because the duplicates section below
  // needs it too: merging removes a document, and this is the only thing that
  // tells the table so.
  const loadDocuments = useCallback(
    () =>
      listDocuments()
        .then(setDocuments)
        .catch((cause: unknown) =>
          setError(messageOf(cause, 'Failed to load documents.')),
        ),
    [],
  )

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  const namesBySlug = useMemo(() => {
    const names = new Map<string, string>()
    for (const document of documents ?? []) names.set(document.slug, document.name)
    return names
  }, [documents])

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const matching = (documents ?? []).filter(
      (d) =>
        // Name **or ID**. The slug is what appears in every citation this product
        // prints, so a reader who has seen a citation has seen a slug — and until
        // STORY-014 could not search for it.
        (!needle ||
          d.name.toLowerCase().includes(needle) ||
          d.slug.toLowerCase().includes(needle)) &&
        (!withText || d.version_count > 0),
    )

    // Sorted on a copy: `documents` is state, and Array.prototype.sort mutates.
    return [...matching].sort((a, b) => {
      const left = sortValue(a, sortKey)
      const right = sortValue(b, sortKey)
      // Names compare as strings, counts as numbers; a plain `<` would order
      // "10" before "9".
      const order =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right))
      // Ties within a count column fall back to the name, so the order does not
      // wander between renders over the 400-odd documents cited exactly once.
      const settled = order !== 0 ? order : a.name.localeCompare(b.name)
      return sortDirection === 'asc' ? settled : -settled
    })
  }, [documents, filter, withText, sortKey, sortDirection])

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  // Clamped at render rather than reset in an effect. The filter can change from
  // outside this component — the nav search box navigates here with a `q` — so
  // there is no single handler that could own the reset, and a `setState` in an
  // effect body is the cascading render the lint rule forbids.
  const currentPage = Math.min(page, pageCount - 1)
  const firstRow = currentPage * PAGE_SIZE
  const shown = useMemo(
    () => visible.slice(firstRow, firstRow + PAGE_SIZE),
    [visible, firstRow],
  )

  function chooseSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection(FIRST_DIRECTION[key])
    }
    setPage(0)
  }

  // Applied to local state rather than by refetching: a refetch after every edit
  // makes a 438-document corpus feel broken, and the API's response already says
  // what changed.
  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true)
    setEditError(null)
    try {
      await action()
    } catch (cause: unknown) {
      setEditError(messageOf(cause, fallback))
    } finally {
      setBusy(false)
    }
  }

  async function onCreate(event: React.FormEvent) {
    event.preventDefault()
    const name = newName.trim()
    // Not a disabled button: a disabled control gives no reason, and the API would
    // reject this anyway. Refusing here keeps a pointless request off the wire.
    //
    // It has to say so, though, and it has to clear whatever was there before.
    // A bare `return` left the *previous* attempt's error standing — press Add on
    // an empty box after a name collision and the screen answers "a document named
    // 'DoDD 5000.01' already exists", which explains something the reader did not
    // just do.
    if (!name) {
      setEditError('Give the document a name before adding it.')
      return
    }

    await run(async () => {
      const created = await createDocument({ name })
      setDocuments((current) => [...(current ?? []), created])
      setNewName('')
    }, 'Could not create the document.')
  }

  async function onDelete(slug: string) {
    await run(async () => {
      await deleteDocument(slug)
      setDocuments((current) => (current ?? []).filter((d) => d.slug !== slug))
      setConfirming(null)
      if (expanded === slug) setExpanded(null)
    }, 'Could not delete the document.')
  }

  async function onAddReference(slug: string, target: string) {
    if (!target) return
    await run(async () => {
      await addReference(slug, target)
      setDocuments((current) =>
        (current ?? []).map((d) =>
          d.slug === slug ? { ...d, references: [...d.references, target] } : d,
        ),
      )
      setReferenceTarget('')
    }, 'Could not add the reference.')
  }

  async function onRemoveReference(slug: string, target: string) {
    await run(async () => {
      await removeReference(slug, target)
      setDocuments((current) =>
        (current ?? []).map((d) =>
          d.slug === slug
            ? { ...d, references: d.references.filter((r) => r !== target) }
            : d,
        ),
      )
    }, 'Could not remove the reference.')
  }

  if (error) return <div role="alert">Could not load documents: {error}</div>
  if (!documents) return <p>Loading documents…</p>

  const addForm = (
    <form onSubmit={onCreate} className="add-document">
      <label htmlFor="new-document-name">Name of the document to add</label>{' '}
      <input
        id="new-document-name"
        value={newName}
        onChange={(event) => setNewName(event.target.value)}
        placeholder="DoDI 5000.02"
      />{' '}
      <button type="submit" disabled={busy}>
        Add document
      </button>
    </form>
  )

  // An empty corpus gets a statement, not a filter over nothing and a table
  // of headers — which reads as a fetch that failed (ADR-019). It still gets the
  // add form: STORY-044 is the answer to "there is nothing here", and a screen
  // that explains emptiness without offering a way out is only half an answer.
  if (documents.length === 0)
    return (
      <div className="view">
        <h1>Documents</h1>
        <EmptyState />
        {addForm}
        {editError && <div role="alert">{editError}</div>}
      </div>
    )

  return (
    <div className="view">
      <h1>Documents</h1>

      {/* The panel itself is below the table. This is what stays at the top —
          one line, because a maintenance task waiting on two of 438 documents
          should not be the first 450 pixels of the screen that lists them. */}
      {duplicatePairs > 0 && (
        <p className="notice">
          <a href="#duplicates">
            {duplicatePairs} near-duplicate name
            {duplicatePairs === 1 ? '' : 's'} need
            {duplicatePairs === 1 ? 's' : ''} a decision
          </a>
        </p>
      )}

      <div className="table-controls">
      <input
        type="search"
        aria-label="Filter documents by name or ID"
        placeholder="Filter by name or ID…"
        value={filter}
        onChange={(event) => {
          setFilter(event.target.value)
          setPage(0)
        }}
      />{' '}
      <label>
        <input
          type="checkbox"
          checked={withText}
          onChange={(event) => {
            setWithText(event.target.checked)
            setPage(0)
          }}
        />{' '}
        Only documents with text
      </label>
      </div>

      {addForm}
      {editError && <div role="alert">{editError}</div>}

      <div className="table-summary">
        <p>
          {visible.length === 0 ? (
            <>Showing 0 of {documents.length}</>
          ) : visible.length > PAGE_SIZE ? (
            <>
              Showing {firstRow + 1}–{firstRow + shown.length} of {visible.length}
            </>
          ) : (
            <>
              Showing {visible.length} of {documents.length}
            </>
          )}
        </p>

        {pageCount > 1 && (
          <p className="pager">
            <button
              type="button"
              onClick={() => setPage(currentPage - 1)}
              disabled={currentPage === 0}
            >
              Previous page
            </button>{' '}
            <span>
              Page {currentPage + 1} of {pageCount}
            </span>{' '}
            <button
              type="button"
              onClick={() => setPage(currentPage + 1)}
              disabled={currentPage >= pageCount - 1}
            >
              Next page
            </button>
          </p>
        )}
      </div>

      {visible.length === 0 ? (
        // STORY-014: it has to say what it looked for. "No documents match that
        // filter" left a reader unable to tell a mistyped search from an empty
        // corpus — the blank that reads as broken, one step removed (ADR-019).
        <p>
          <strong>No document matches “{filter}”.</strong> Searching covers a
          document&rsquo;s name and its ID — the slug that appears in citations,
          like <code>dodd-5000-01</code>.
        </p>
      ) : (
        /* Wrapped so a narrow window scrolls the table rather than crushing five
           columns of nested controls into unreadable slivers. */
        <div className="table-scroll">
        <table className="documents">
          {/* Column widths belong to the table, not to each cell. Without them
              the browser sizes from content and gives the Actions column as much
              room as the names. */}
          <colgroup>
            <col className="col-name" />
            <col className="col-count" />
            <col className="col-count" />
            <col className="col-references" />
            <col className="col-actions" />
          </colgroup>
          <thead>
            <tr>
              {/* `aria-sort` on the header, the control inside it. A `<th>` is
                  not interactive and a screen reader announces the column's sort
                  state from the cell, not from the button that changes it. */}
              {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                <th
                  key={key}
                  aria-sort={
                    sortKey === key
                      ? sortDirection === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                  }
                >
                  <button
                    type="button"
                    className="sort"
                    aria-label={`Sort by ${SORT_LABELS[key]}`}
                    onClick={() => chooseSort(key)}
                  >
                    {SORT_LABELS[key]}
                    <span aria-hidden="true">
                      {sortKey === key ? (sortDirection === 'asc' ? ' ↑' : ' ↓') : ' ↕'}
                    </span>
                  </button>
                </th>
              ))}
              <th>References</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((document) => (
              <tr key={document.slug}>
                <td>
                  {/* STORY-017's detail view is reached from here: the table is the
                      only place a reader already has the document in front of them. */}
                  <Link to={`/documents/${document.slug}`}>{document.name}</Link>
                  {document.is_external && <span> (external)</span>}
                </td>
                {/* ADR-006: standing among other documents is read off the edges. */}
                <td>{document.referenced_by.length}</td>
                <td>{document.version_count}</td>
                <td>
                  {document.references
                    .map((slug) => namesBySlug.get(slug) ?? slug)
                    .join(', ')}
                  <div>
                    <button
                      type="button"
                      aria-expanded={expanded === document.slug}
                      /* The name lives in the accessible label, not in the visible
                         text. Printing it in both put the document's full name in
                         every row three times over — "References of Adaptive
                         Acquisition Framework Documentation Identification (AAFDID)
                         Tool" as a button caption — which pushed the Name column
                         itself down to a two-line wrap. Screen readers still hear
                         which document each control belongs to. */
                      aria-label={`References of ${document.name}`}
                      onClick={() => {
                        setExpanded(expanded === document.slug ? null : document.slug)
                        setReferenceTarget('')
                      }}
                    >
                      References
                    </button>
                  </div>

                  {expanded === document.slug && (
                    <div>
                      <ul>
                        {document.references.map((target) => (
                          <li key={target}>
                            {namesBySlug.get(target) ?? target}{' '}
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => onRemoveReference(document.slug, target)}
                            >
                              Remove reference to {namesBySlug.get(target) ?? target}
                            </button>
                          </li>
                        ))}
                      </ul>

                      <label htmlFor={`reference-target-${document.slug}`}>
                        Document {document.name} should reference
                      </label>{' '}
                      <select
                        id={`reference-target-${document.slug}`}
                        value={referenceTarget}
                        onChange={(event) => setReferenceTarget(event.target.value)}
                      >
                        <option value="">Choose a document…</option>
                        {documents
                          // A document referencing itself is the one edge ingest
                          // already discards (`self_references_skipped`), so it must
                          // not be offerable here either.
                          .filter(
                            (other) =>
                              other.slug !== document.slug &&
                              !document.references.includes(other.slug),
                          )
                          .map((other) => (
                            <option key={other.slug} value={other.slug}>
                              {other.name}
                            </option>
                          ))}
                      </select>{' '}
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onAddReference(document.slug, referenceTarget)}
                      >
                        Add reference
                      </button>
                    </div>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Delete ${document.name}`}
                    onClick={() => setConfirming(document.slug)}
                  >
                    Delete
                  </button>

                  {confirming === document.slug && (
                    // Destructive and irreversible, so it names the document and says
                    // what goes with it. A confirmation that says "Are you sure?" and
                    // nothing else transfers no information.
                    <div role="dialog" aria-label={`Delete ${document.name}`}>
                      <p>
                        Delete <strong>{document.name}</strong>? Its references to and
                        from other documents go with it. Documents that only exist
                        because this one cited them remain.
                      </p>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onDelete(document.slug)}
                      >
                        Delete
                      </button>{' '}
                      <button type="button" onClick={() => setConfirming(null)}>
                        Cancel
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      {/* Below the corpus it is about. Reconciling two records of one document
          is real work and it keeps a real section — but it is work about a
          handful of names, and it used to open a screen whose job is listing
          438 documents. The line at the top links here. */}
      <section id="duplicates" className="duplicates">
        <Duplicates onMerged={loadDocuments} onCount={setDuplicatePairs} />
      </section>
    </div>
  )
}
