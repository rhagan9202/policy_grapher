import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ingest, listSources } from '../api/client'
import type { IngestResult, SourceFile } from '../api/types'
import type { ArrivedFromIngest } from './GraphExplorer'

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
  const navigate = useNavigate()
  // Whether the reader is still here. An ingest resolves in the foreground but
  // not instantly, and the navigation stays available while it runs — so they
  // can leave for another screen mid-request. `useNavigate` is bound to the
  // router, not to this component, so the continuation below would still fire
  // and haul them back to a document they had already moved on from.
  //
  // Set true in the effect body, not only false in the cleanup. StrictMode
  // mounts, unmounts and remounts every effect in development, so a cleanup
  // that is never undone leaves this false for the life of the screen — and
  // the navigation below is refused on every ingest, in exactly the mode the
  // analyst and every demo run.
  const onThisScreen = useRef(true)
  useEffect(() => {
    onThisScreen.current = true
    return () => {
      onThisScreen.current = false
    }
  }, [])
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
      const written = await ingest(name)
      if (written.source === 'document') {
        // F1, closed. The write and the reader seeing it were two screens and a
        // search apart, and the response already names the document, so nothing
        // has to be looked up to put them on its map.
        //
        // What happened to the write travels with them. The durable account is
        // the node itself — its tier, what its parse made of its references,
        // and the names that went unattributed are all drawn there and survive
        // a reload — but a reader who has just pressed Ingest is owed the
        // immediate one too, and the navigation that serves them would
        // otherwise discard it. The counts do not travel: a skipped write has
        // none, and for a real one the drawing is the better account of what
        // landed.
        //
        // Not if they have left: a navigation nobody asked for, landing on a
        // document they chose to walk away from, is worse than never hearing
        // the outcome of a write they abandoned.
        if (!onThisScreen.current) return
        navigate(`/?focus=${written.document.slug}`, {
          state: {
            // Typed against the reader's own declaration rather than built as a
            // bare literal: producer and consumer are in different files, and a
            // renamed field would otherwise compile on both sides and go missing
            // at runtime.
            ingest: {
              outcome: written.outcome,
              slug: written.document.slug,
              name: written.document.name,
              versionId: written.version_id,
              unresolved: written.references_unattributed,
            } satisfies ArrivedFromIngest,
          },
        })
        return
      }
      setResult(written)
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Ingest failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="view">
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
          {/* Manifests only. A document ingest does not report here at all:
              it sends the reader to that document's map, where the account of
              the write travels with them and the drawing itself is the better
              statement of what landed. A manifest is many documents at once,
              with no one slug to focus, so it has nowhere else to go. */}
          {result.source === 'manifest' && (
            <>
              <h2>Ingested a manifest</h2>
              <ul>
                <li>{result.nodes_created} nodes created</li>
                <li>{result.relationships_created} relationships created</li>
                <li>{result.self_references_skipped} self-references skipped</li>
              </ul>

              {result.suspected_duplicates.length > 0 && (
                <>
                  {/* STORY-003 flags these and STORY-031 built the screen that
                      rules on them. Naming them here and stopping left the reader
                      holding a finding with nowhere to take it — the control is
                      one click away and nothing said so. */}
                  <h3>
                    {result.suspected_duplicates.length} suspected duplicate names
                  </h3>
                  <ul>
                    {result.suspected_duplicates.map((group) => (
                      <li key={group.join('|')}>{group.join(' / ')}</li>
                    ))}
                  </ul>
                  <p>
                    Names differing only by punctuation or spacing may be one
                    document held as two, which divides its references between
                    them. Rule on each pair under{' '}
                    <Link to="/documents">Documents</Link>. Nothing is merged
                    automatically.
                  </p>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
