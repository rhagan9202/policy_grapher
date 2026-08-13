import { useEffect, useMemo, useState } from 'react'
import { listDocuments } from '../api/client'
import type { DocumentOut } from '../api/types'

export default function DocumentTable() {
  const [documents, setDocuments] = useState<DocumentOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  useEffect(() => {
    let cancelled = false

    listDocuments()
      .then((result) => {
        if (!cancelled) setDocuments(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load documents.')
        }
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

  if (error) return <div role="alert">Could not load documents: {error}</div>
  if (!documents) return <p>Loading documents…</p>

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
            </tr>
          </thead>
          <tbody>
            {visible.map((document) => (
              <tr key={document.slug}>
                <td>
                  <span>{document.name}</span>
                  {document.is_external && <span> (external)</span>}
                </td>
                {/* ADR-006: standing among other documents is read off the edges. */}
                <td>{document.referenced_by.length}</td>
                <td>
                  {document.references
                    .map((slug) => namesBySlug.get(slug) ?? slug)
                    .join(', ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
