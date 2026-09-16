/** A render that throws used to take the whole application with it.
 *
 * Measured before this existed: an API answering `{"items": []}` where an array
 * was expected threw `(documents ?? []) is not iterable` inside `DocumentTable`,
 * React unmounted the entire tree, and the page went white — navigation
 * included, no message, no way back but a reload. Any schema drift, partial
 * response, or unhandled render exception on any screen produced the same blank
 * page, which reads to a viewer as "the product does not exist".
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ErrorBoundary from './ErrorBoundary'

function Boom(): never {
  throw new Error('(documents ?? []) is not iterable')
}

describe('ErrorBoundary', () => {
  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <p>the screen</p>
      </ErrorBoundary>,
    )

    expect(screen.getByText('the screen')).toBeInTheDocument()
  })

  it('replaces a screen that threw with a named failure', () => {
    // React re-throws to the console on the way past. Silenced so that a passing
    // run does not print a stack trace that looks like a failure.
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/this screen failed to render/i)).toBeInTheDocument()
    // The message itself, because "something went wrong" is not a thing anyone
    // can act on or report.
    expect(screen.getByText(/is not iterable/)).toBeInTheDocument()

    logged.mockRestore()
  })

  it('contains the failure instead of taking the page with it', () => {
    const logged = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <>
        <nav aria-label="Main">the navigation</nav>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </>,
    )

    // The whole point: the reader can still leave the broken screen.
    expect(screen.getByText('the navigation')).toBeInTheDocument()

    logged.mockRestore()
  })
})
