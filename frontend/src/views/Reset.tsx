import { useState } from 'react'
import { reset } from '../api/client'
import type { ResetResult } from '../api/types'

// The phrase a reader has to type. Long enough not to be muscle memory, and it says
// what it does rather than being a ritual word like "DELETE".
const CONFIRMATION = 'empty the graph'

// STORY-046. `POST /reset` and `reset()` were both built and unreachable.
//
// The confirmation carries the weight here, and the plan's risk note is the reason
// it is worded carefully: a confirmation that describes this wrongly is worse than
// no confirmation at all. `clear_graph` removes every node and relationship —
// including the `:EmbeddingIndex` marker — but it cannot delete a Neo4j index, which
// is exactly why `ensure_vector_index` drops and rebuilds one rather than trusting
// `IF NOT EXISTS` (ADR-016). "Everything is deleted" would be false.
export default function Reset() {
  const [confirming, setConfirming] = useState(false)
  const [typed, setTyped] = useState('')
  const [result, setResult] = useState<ResetResult | null>(null)
  const [mismatch, setMismatch] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onReset() {
    // The button is deliberately not disabled while the phrase is unmatched, but a
    // press that does nothing and says nothing is indistinguishable from a broken
    // one — the reader cannot tell "I typed it wrong" from "this screen does not
    // work". The comment below used to claim the reason stayed on screen; the only
    // thing on screen was the instruction, which is what they had just tried to
    // follow.
    if (typed.trim().toLowerCase() !== CONFIRMATION) {
      setMismatch(true)
      return
    }
    setMismatch(false)

    setBusy(true)
    setError(null)
    try {
      setResult(await reset())
      setConfirming(false)
      setTyped('')
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Reset failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Reset</h1>

      <p>
        Empties the graph: every document, edition, chunk, obligation, proposal and
        recorded decision. There is no undo and no export.
      </p>

      <button type="button" onClick={() => setConfirming(true)} disabled={busy}>
        Empty the graph
      </button>

      {error && <div role="alert">Reset failed: {error}</div>}

      {result && (
        <div role="status">
          <p>
            Deleted {result.nodes_deleted} nodes and{' '}
            {result.relationships_deleted} relationships.
          </p>
        </div>
      )}

      {confirming && (
        <div role="dialog" aria-label="Confirm emptying the graph">
          <p>
            This <strong>cannot be undone</strong>. Every document, edition, chunk,
            obligation, proposal and recorded review decision is deleted — including
            decisions, which a rebuild replays and therefore cannot bring back once
            they are gone.
          </p>
          <p>
            The Neo4j <strong>vector index</strong> is not deleted, because a reset
            cannot delete one. It is left holding the geometry of whatever embedder
            wrote it, and is dropped and rebuilt on the next embed rather than trusted
            (ADR-016).
          </p>

          <label htmlFor="reset-confirmation">
            Type <code>{CONFIRMATION}</code> to confirm
          </label>{' '}
          <input
            id="reset-confirmation"
            value={typed}
            onChange={(event) => {
              setTyped(event.target.value)
              setMismatch(false)
            }}
            autoComplete="off"
          />

          {mismatch && (
            <p role="alert">
              That is not the phrase. Nothing has been deleted — type{' '}
              <code>{CONFIRMATION}</code> exactly.
            </p>
          )}

          <p>
            {/* Deliberately not disabled while the phrase is unmatched: a disabled
                button explains nothing. Pressing it without the phrase deletes
                nothing and says why, which a disabled control could not do. */}
            <button type="button" onClick={onReset} disabled={busy}>
              Delete everything
            </button>{' '}
            <button
              type="button"
              onClick={() => {
                setConfirming(false)
                setTyped('')
                setMismatch(false)
              }}
            >
              Cancel
            </button>
          </p>
        </div>
      )}
    </div>
  )
}
