import { useEffect, useState } from 'react'
import { ingest, listSources } from '../api/client'
import type { IngestResult, SourceFile } from '../api/types'

/** What ingest will make of a file, in the words the screen's own prose uses.
 *
 *  Read off the extension rather than only the kind, since STORY-036: the backend
 *  reports `manifest` for both a CSV and a spreadsheet, and calling an `.xlsx` a
 *  "CSV manifest" is the same defect this picker exists to fix — a reader who
 *  cannot tell what a file is. Found by ingesting one and reading the label. */
const MANIFEST_LABELS: Record<string, string> = {
  csv: 'CSV manifest',
  xlsx: 'spreadsheet manifest',
}

function describeKind(file: { filename: string; kind: string }): string {
  if (file.kind === 'document') return 'PDF document'
  if (file.kind !== 'manifest') return file.kind
  const extension = file.filename.split('.').pop()?.toLowerCase() ?? ''
  return MANIFEST_LABELS[extension] ?? 'manifest'
}

/** Readable at a glance, which "1463 KB" is not. */
function humanSize(bytes: number): string {
  const kb = bytes / 1024
  return kb >= 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${Math.round(kb)} KB`
}

function describe(source: SourceFile): string {
  const kind = describeKind(source)
  const already = source.ingested ? ' · already ingested' : ''
  return `${source.filename} — ${kind} · ${humanSize(source.size_bytes)}${already}`
}

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

  // What the backend can be given. `null` until the listing answers.
  const [sources, setSources] = useState<SourceFile[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)

  // async/await rather than .then/.catch: a caller that has not stubbed
  // `listSources` gets `undefined` back, and `.catch` on undefined throws
  // outside any guard. The same shape bit DocumentDetail's name lookup.
  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const found = await listSources()
        if (!cancelled) setSources(found ?? [])
      } catch (cause: unknown) {
        if (!cancelled) {
          setListError(
            cause instanceof Error ? cause.message : 'Could not list the data directory.',
          )
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

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
        What the backend can read from its own data directory. A manifest — a CSV
        or a spreadsheet — lists
        documents and the references between them; a PDF issuance carries one
        document and its text. Nothing is uploaded from this machine — the file has
        to be in that directory already.
      </p>

      {listError && (
        // The picker could not load, so the reader falls back to naming the file
        // themselves. A control that cannot load must not leave them with no way
        // to act at all.
        <div role="alert">
          Could not list the data directory: {listError}. Type a filename instead.
        </div>
      )}

      {sources !== null && sources.length === 0 && (
        <div role="status">
          <p>
            <strong>No files to ingest.</strong> The backend is reading{' '}
            <code>DATA_DIR</code> inside its own container, and that directory is
            empty. Put a manifest (CSV or spreadsheet) or a PDF issuance there and
            reload.
          </p>
        </div>
      )}

      <form onSubmit={onSubmit}>
        <label htmlFor="ingest-filename">File to ingest</label>{' '}
        {sources === null && !listError ? (
          // Neither a picker nor a text box until the listing answers. Showing
          // the fallback input here would offer a control the reader is about
          // to lose, and reads as though typing were the intended way in.
          <span>Loading the file list…</span>
        ) : sources !== null && sources.length > 0 ? (
          <select
            id="ingest-filename"
            value={filename}
            onChange={(event) => setFilename(event.target.value)}
          >
            <option value="">Choose a file…</option>
            {sources.map((source) => (
              <option key={source.filename} value={source.filename}>
                {describe(source)}
              </option>
            ))}
          </select>
        ) : (
          <input
            id="ingest-filename"
            value={filename}
            onChange={(event) => setFilename(event.target.value)}
            placeholder="dod_policy_references_08122026.csv"
            size={40}
          />
        )}{' '}
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
                <li>
                  edition <code>{result.version_id}</code>, {result.chunks_written} chunks
                  of text
                </li>
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
