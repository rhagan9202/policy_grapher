import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { getDocument, listChunks, listVersions } from '../api/client'
import type { ChunkOut, DocumentOut, DocumentVersionOut } from '../api/types'

// STORY-017, the "corpus management" MVP item. `GET /documents/{slug}/chunks` has
// served ordered text with `page` and `section_path` since ADR-012, and `client.ts`
// had no function for the route at all — so nothing in the UI could read a
// document's text. This screen is the caller for that route, and for `getDocument`
// and `listVersions`.
export default function DocumentDetail() {
  const { slug = '' } = useParams()

  const [document, setDocument] = useState<DocumentOut | null>(null)
  const [versions, setVersions] = useState<DocumentVersionOut[]>([])
  const [chunks, setChunks] = useState<ChunkOut[] | null>(null)
  const [edition, setEdition] = useState<string | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    Promise.all([getDocument(slug), listVersions(slug)])
      .then(([found, editions]) => {
        if (cancelled) return
        setDocument(found)
        setVersions(editions)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load document.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [slug])

  // Separate from the document fetch because it re-runs when the edition changes.
  // `edition` starts undefined, which the API reads as "newest" — the right default,
  // and one the client should not try to compute for itself.
  useEffect(() => {
    let cancelled = false

    listChunks(slug, edition)
      .then((result) => {
        if (!cancelled) setChunks(result)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load text.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [slug, edition])

  if (error) return <div role="alert">Could not load this document: {error}</div>
  if (!document) return <p>Loading document…</p>

  return (
    <div style={{ padding: '1rem' }}>
      <h1>
        {document.name}
        {document.is_external && <span> (external)</span>}
      </h1>
      <p>
        <code>{document.slug}</code>
      </p>

      <h2 id="references-heading">References</h2>
      {document.references.length === 0 ? (
        <p>This document cites nothing in the corpus.</p>
      ) : (
        <ul aria-labelledby="references-heading">
          {document.references.map((target) => (
            <li key={target}>{target}</li>
          ))}
        </ul>
      )}

      <h2>Text</h2>

      {versions.length > 0 && (
        <p>
          <label htmlFor="edition">Edition</label>{' '}
          <select
            id="edition"
            value={edition ?? ''}
            onChange={(event) => setEdition(event.target.value || undefined)}
          >
            <option value="">Newest</option>
            {versions.map((version) => (
              <option key={version.version_id} value={version.version_id}>
                {version.effective_date} ({version.version_id})
              </option>
            ))}
          </select>
        </p>
      )}

      {chunks === null ? (
        <p>Loading text…</p>
      ) : chunks.length === 0 ? (
        // The state the sample CSV produces for all 438 of its documents: a
        // manifest records no text (ADR-011). Sprint 3's walkthrough found a defect
        // of exactly this shape in Triage — a control rendered empty and
        // unexplained — so this says which of the two it is.
        <p>
          This document has <strong>no ingested text</strong>. It was recorded from a
          manifest, which lists documents and references but carries no document
          body. Ingest the source PDF to read it here.
        </p>
      ) : (
        <article>
          {chunks.map((chunk) => (
            <section key={chunk.chunk_id}>
              <h3>
                {chunk.section_path.join(' / ') || '(preamble)'} — page {chunk.page}
              </h3>
              <p style={{ whiteSpace: 'pre-wrap' }}>{chunk.text}</p>
            </section>
          ))}
        </article>
      )}
    </div>
  )
}
