import { useState } from 'react'
import { ingest } from '../api/client'
import type { IngestResult } from '../api/types'

// STORY-043. `POST /ingest` has existed since DI-1 and nothing called it, so loading
// the corpus was a curl command — which means the person this tool is for could not
// put a document into it.
//
// The route takes a filename rather than an upload: the backend reads from
// `DATA_DIR` inside its own container, which is a deliberate constraint and not one
// this screen can paper over. Saying so is better than a file picker that appears to
// upload and does not.
export default function Ingest() {
  const [filename, setFilename] = useState('')
  const [result, setResult] = useState<IngestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    const name = filename.trim()
    if (!name) return

    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await ingest(name))
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Ingest failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Ingest</h1>

      <p>
        The name of a file in the backend&apos;s data directory — a CSV manifest of
        documents and references, or a PDF issuance. The file is read inside the
        backend container, so it must already be there.
      </p>

      <form onSubmit={onSubmit}>
        <label htmlFor="ingest-filename">File to ingest</label>{' '}
        <input
          id="ingest-filename"
          value={filename}
          onChange={(event) => setFilename(event.target.value)}
          placeholder="dod_policy_references_08122026.csv"
          size={40}
        />{' '}
        <button type="submit" disabled={busy}>
          {busy ? 'Ingesting…' : 'Ingest'}
        </button>
      </form>

      {error && <div role="alert">Ingest failed: {error}</div>}

      {result && (
        // `status` rather than `alert`: this is the outcome of something the reader
        // just asked for, not an interruption.
        <div role="status">
          {result.source === 'document' ? (
            <>
              <h2>
                Ingested {result.document.name} ({result.format} format)
              </h2>
              <ul>
                <li>{result.nodes_created} nodes created</li>
                <li>{result.relationships_created} relationships created</li>
                <li>{result.references_attributed} references attributed</li>
                <li>{result.self_references_skipped} self-references skipped</li>
              </ul>

              {result.references_unattributed.length > 0 && (
                <>
                  {/* Named, not counted. An unattributed reference is a citation the
                      graph does not hold, and a number alone says something is
                      missing without saying what. */}
                  <h3>
                    {result.references_unattributed.length} references could not be
                    attributed to a document
                  </h3>
                  <ul>
                    {result.references_unattributed.map((reference) => (
                      <li key={reference}>{reference}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          ) : (
            <>
              <h2>Ingested a manifest</h2>
              <ul>
                <li>{result.nodes_created} nodes created</li>
                <li>{result.relationships_created} relationships created</li>
                <li>{result.self_references_skipped} self-references skipped</li>
              </ul>

              {result.suspected_duplicates.length > 0 && (
                <>
                  {/* STORY-003 flags these; nothing merges them (STORY-031). Showing
                      them is the whole of what the product currently offers. */}
                  <h3>
                    {result.suspected_duplicates.length} suspected duplicate names
                  </h3>
                  <ul>
                    {result.suspected_duplicates.map((group) => (
                      <li key={group.join('|')}>{group.join(' / ')}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
