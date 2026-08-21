import { useState } from 'react'
import { ask } from '../api/client'
import type { Answer } from '../api/types'

export default function Ask() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

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
                    <cite>
                      {citation.document} · {citation.section_path.join('/')} · p.{' '}
                      {citation.page}
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
    </div>
  )
}
