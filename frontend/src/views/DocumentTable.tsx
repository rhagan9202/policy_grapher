import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
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

export default function DocumentTable() {
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

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

  useEffect(() => {
    let cancelled = false

    listDocuments()
      .then((result) => {
        if (!cancelled) setDocuments(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(messageOf(cause, 'Failed to load documents.'))
      })

    return () => {
      cancelled = true
    }
  }, [])

  const namesBySlug = useMemo(() => {
    const names = new Map<string, string>()
    for (const document of documents ?? []) names.set(document.slug, document.name)
    return names
  }, [documents])

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    if (!needle) return documents ?? []
    return (documents ?? []).filter((d) => d.name.toLowerCase().includes(needle))
  }, [documents, filter])

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
    if (!name) return

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
    <form onSubmit={onCreate} style={{ margin: '1rem 0' }}>
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
      <div style={{ padding: '1rem' }}>
        <h1>Documents</h1>
        <EmptyState />
        {addForm}
        {editError && <div role="alert">{editError}</div>}
      </div>
    )

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Documents</h1>

      <input
        type="search"
        aria-label="Filter documents by name"
        placeholder="Filter by name…"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
      />

      {addForm}
      {editError && <div role="alert">{editError}</div>}

      <p>
        Showing {visible.length} of {documents.length}
      </p>

      {visible.length === 0 ? (
        <p>No documents match that filter.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Cited by</th>
              <th>References</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((document) => (
              <tr key={document.slug}>
                <td>
                  {/* STORY-017's detail view is reached from here: the table is the
                      only place a reader already has the document in front of them. */}
                  <Link to={`/documents/${document.slug}`}>{document.name}</Link>
                  {document.is_external && <span> (external)</span>}
                </td>
                {/* ADR-006: standing among other documents is read off the edges. */}
                <td>{document.referenced_by.length}</td>
                <td>
                  {document.references
                    .map((slug) => namesBySlug.get(slug) ?? slug)
                    .join(', ')}
                  <div>
                    <button
                      type="button"
                      aria-expanded={expanded === document.slug}
                      onClick={() => {
                        setExpanded(expanded === document.slug ? null : document.slug)
                        setReferenceTarget('')
                      }}
                    >
                      References of {document.name}
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
                    onClick={() => setConfirming(document.slug)}
                  >
                    Delete {document.name}
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
      )}
    </div>
  )
}
