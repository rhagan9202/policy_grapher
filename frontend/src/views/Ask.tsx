import { useEffect, useState } from 'react'
import { ask, listDocuments } from '../api/client'
import EmptyState from './EmptyState'
import type { Answer } from '../api/types'

export default function Ask() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [corpusEmpty, setCorpusEmpty] = useState<boolean | null>(null)

  // Asking a question of an empty corpus can only ever answer "nothing in the
  // corpus says", which is indistinguishable from a real negative finding.
  // Better to say the corpus is empty before the question is asked.
  useEffect(() => {
    let cancelled = false
    listDocuments()
      .then((d) => {
        if (!cancelled) setCorpusEmpty(d.length === 0)
      })
      .catch(() => {
        if (!cancelled) setCorpusEmpty(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function submit() {
    if (!question.trim()) return
    setPending(true)
    setError(null)
    try {
      setAnswer(await ask(question))
    } catch (cause: unknown) {
      setAnswer(null)
      setError(cause instanceof Error ? cause.message : 'Failed to ask.')
    } finally {
      setPending(false)
    }
  }

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Ask</h1>

      {corpusEmpty ? (
        <EmptyState lead="There is nothing to ask about." />
      ) : (
      <>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <input
          type="search"
          aria-label="Question"
          placeholder="What obliges the Director?"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />{' '}
        <button type="submit" disabled={pending}>
          Ask
        </button>
      </form>

      {error && <div role="alert">Could not answer: {error}</div>}

      {answer && (
        <article>
          {/* The answer is composed from the citations below it (ADR-017), so
              whitespace is meaningful — it is a list of quotations, not prose. */}
          <p style={{ whiteSpace: 'pre-wrap' }}>{answer.answer}</p>

          {answer.citations.length > 0 && (
            <>
              <h2>Sources</h2>
              <ul>
                {answer.citations.map((citation, index) => (
                  <li key={`${citation.document}-${citation.page}-${index}`}>
                    <blockquote>{citation.quote}</blockquote>
                    {/* The edition is not decoration. A corpus holding both the
                        2003 and 2020 editions of one directive answers out of
                        both, and "DoDD 5000.01 · p. 1" names a passage in each —
                        one of them superseded. */}
                    <cite>
                      {citation.document} · {citation.version_id} ·{' '}
                      {citation.section_path.join('/')} · p. {citation.page}
                    </cite>
                  </li>
                ))}
              </ul>
            </>
          )}

          <p>
            <small>Answered by: {answer.template_used}</small>
          </p>
        </article>
      )}
      </>
      )}
    </div>
  )
}
