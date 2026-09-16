import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Keeps one screen's render failure from taking the application with it.
 *
 * There was no boundary anywhere in this app, so an exception thrown during
 * render unmounted the whole tree and left a white page — navigation included.
 * Measured: an API answering `{"items": []}` where an array was expected threw
 * `(documents ?? []) is not iterable` in `DocumentTable`, and the result was
 * indistinguishable from the product not being deployed. ADR-019 forbids a blank
 * that reads as a failure on an empty corpus; a blank that reads as a failure
 * because the app *has* failed deserves at least as much.
 *
 * A class because React offers no hook equivalent: `getDerivedStateFromError`
 * and `componentDidCatch` are the entire API.
 *
 * Deliberately shows the message. "Something went wrong" cannot be acted on or
 * reported, and this text is the only account of the failure a user will have —
 * the console is not somewhere an analyst is asked to look.
 */

type Props = { children: ReactNode }
type State = { message: string | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null }

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    // The stack is worth keeping for whoever opens devtools, even though the
    // paragraph above is what the reader gets.
    console.error('A screen failed to render', error, info)
  }

  render() {
    if (this.state.message === null) {
      return this.props.children
    }
    return (
      <div className="view" role="alert">
        <p>
          <strong>This screen failed to render.</strong> The rest of the
          application is still working — pick another screen from the navigation
          above, or reload to try this one again.
        </p>
        <p>
          <code>{this.state.message}</code>
        </p>
      </div>
    )
  }
}
