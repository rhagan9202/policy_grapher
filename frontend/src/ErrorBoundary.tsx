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

/** `resetKey` clears a caught failure when it changes — pass the current
 *  location. It is a prop and not React's `key` for a reason both halves of
 *  which were found in review.
 *
 *  As `key` on this component it was too coarse *and* too fine at once. Too
 *  coarse because a `key` of the path alone ignores the query string, so a
 *  render that threw on `/documents?q=X` stayed caught while the reader typed a
 *  new search term — the app's own search could not recover from a crash it had
 *  triggered. Too fine because a `key` that does change remounts the whole
 *  subtree: navigating between two documents threw away `DocumentDetail`'s state
 *  and re-ran its corpus-wide fetch, which the guards in that file exist
 *  precisely to make unnecessary.
 *
 *  Comparing in `componentDidUpdate` separates the two: the subtree keeps its
 *  identity across every navigation, and only a *caught* boundary resets. */
type Props = {
  children: ReactNode
  resetKey: string
  /** Whether the navigation survives this boundary catching. False for the root
   *  instance in `main.tsx`, which sits outside the chrome — telling that reader
   *  to "pick another screen from the navigation above" points at something the
   *  failure took with it. */
  hasNavigation?: boolean
}
type State = { message: string | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null }

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) }
  }

  componentDidUpdate(previous: Props) {
    if (previous.resetKey !== this.props.resetKey && this.state.message !== null) {
      this.setState({ message: null })
    }
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
          <strong>This screen failed to render.</strong>{' '}
          {this.props.hasNavigation === false
            ? 'Reload the page to try again.'
            : 'The rest of the application is still working — pick another screen from the navigation above, or reload to try this one again.'}
        </p>
        <p>
          <code>{this.state.message}</code>
        </p>
      </div>
    )
  }
}
