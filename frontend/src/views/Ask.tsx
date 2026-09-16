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
    <div className="view">
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
          <p className="answer">{answer.answer}</p>

          {answer.citations.length > 0 && (
            <>
              <h2>Sources</h2>
              {/* Where each passage came from, in the order the answer quotes
                  them — not the passages again. The answer is composed from
                  these citations (ADR-017), so their text is already above,
                  verbatim and identically truncated; printing it a second time
                  doubled the length of every answer and told the reader nothing
                  they had not just read. ADR-017's requirement is that an answer
                  carry its citations, and this is them. */}
              <ol className="citations">
                {answer.citations.map((citation, index) => (
                  <li key={`${citation.document}-${citation.page}-${index}`}>
                    {/* The edition is not decoration. A corpus holding both the
                        2003 and 2020 editions of one directive answers out of
                        both, and "DoDD 5000.01 · p. 1" names a passage in each —
                        one of them superseded. */}
                    <cite className="citation">
                      <span className="citation-document">{citation.document}</span>
                      <code>{citation.version_id}</code>
                      <span>{citation.section_path.join('/')}</span>
                      <span>p. {citation.page}</span>
                      {/* The answer groups on this, but the Sources list is read
                          on its own — someone copying a reference out of it
                          should not have to scroll back up to find out which
                          half of the answer it came from. */}
                      {!citation.grounded && (
                        <span className="citation-ungrounded">
                          near in meaning only
                        </span>
                      )}
                    </cite>
                  </li>
                ))}
              </ol>
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
