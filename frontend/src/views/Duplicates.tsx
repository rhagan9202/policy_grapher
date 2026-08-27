import { useCallback, useEffect, useState } from 'react'
import { listDuplicates, markNotDuplicates, mergeDocuments } from '../api/client'
import type { DuplicateCandidate } from '../api/types'

/**
 * Reconciling two records of one document — STORY-031, ADR-032.
 *
 * Ingest has flagged near-duplicate names since STORY-003 and nothing acted on
 * the flag, so one issuance cited two ways stayed two nodes with its references
 * divided between them. The corpus produces two such pairs today.
 *
 * A person decides, always. The unbounded part of entity resolution is deciding
 * *automatically* that two names denote one document — `DoDD 5000.01` and
 * `DoDD 5000.02` differ by one character and are different documents — and this
 * project already refuses to let a machine settle what a human should.
 */
export default function Duplicates() {
  const [pairs, setPairs] = useState<DuplicateCandidate[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  // `.then` rather than `await`: the lint rule reads a `setState` in an async
  // function body as a synchronous one, and a cascading render is the failure it
  // is guarding against. `Review.tsx` loads its queue the same way.
  const load = useCallback(
    () =>
      listDuplicates()
        .then(setPairs)
        .catch((cause: unknown) =>
          setError(
            cause instanceof Error ? cause.message : 'Could not load duplicates.',
          ),
        ),
    [],
  )

  useEffect(() => {
    void load()
  }, [load])

  async function act(action: () => Promise<unknown>) {
    setPending(true)
    setError(null)
    try {
      await action()
      await load()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'That did not work.')
    } finally {
      setPending(false)
    }
  }

  if (!pairs && !error) return <p>Looking for near-duplicate names…</p>
  if (pairs && pairs.length === 0) {
    return (
      <p>
        No unreconciled near-duplicate names. Ingest flags names that differ only
        by punctuation or spacing; every pair it flagged has been ruled on.
      </p>
    )
  }

  return (
    <section>
      <h2>Possible duplicates</h2>
      <p>
        These names differ only by punctuation or spacing, so they may be one
        document held as two — which divides its references between them. Nothing
        is merged automatically.
      </p>

      {error && <div role="alert">{error}</div>}

      {(pairs ?? []).map((pair) => (
        <article key={pair.names.join('|')}>
          <ul>
            {pair.names.map((name, i) => (
              <li key={name}>
                <strong>{name}</strong> — cited by {pair.cited_by[i]}
                {pair.has_text[i] ? ', has ingested text' : ', no ingested text'}
              </li>
            ))}
          </ul>

          {pair.mergeable ? (
            <p>
              {pair.names.map((name, i) => (
                <button
                  key={name}
                  type="button"
                  disabled={pending}
                  onClick={() =>
                    act(() => mergeDocuments(name, pair.names[1 - i]))
                  }
                >
                  Keep “{name}”
                </button>
              ))}
              <button
                type="button"
                disabled={pending}
                onClick={() => act(() => markNotDuplicates(pair.names[0], pair.names[1]))}
              >
                These are different
              </button>
            </p>
          ) : (
            <p>
              <strong>Cannot be merged.</strong> One of these carries ingested
              text, and merging documents that hold text is not attempted — an
              obligation&rsquo;s identity includes the edition it came from, so its
              owner cannot simply change.{' '}
              <button
                type="button"
                disabled={pending}
                onClick={() => act(() => markNotDuplicates(pair.names[0], pair.names[1]))}
              >
                These are different
              </button>
            </p>
          )}
        </article>
      ))}
    </section>
  )
}
