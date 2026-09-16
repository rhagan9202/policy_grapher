import { useEffect, useState } from 'react'
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useSearchParams,
} from 'react-router-dom'
import { ApiError, getHealth } from './api/client'
import ErrorBoundary from './ErrorBoundary'
import { ROUTES } from './routes'
import DocumentDetail from './views/DocumentDetail'


/** The query parameter the Documents table reads its filter from. */
export const SEARCH_PARAM = 'q'

function SearchDocuments() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { pathname } = useLocation()
  // Controlled from the URL while on Documents, so a search survives a reload and
  // the box agrees with what the table is showing. Local elsewhere, because the
  // URL of another screen says nothing about a document search.
  const applied = pathname === '/documents' ? (params.get(SEARCH_PARAM) ?? '') : ''

  // Uncontrolled and keyed on the applied term rather than mirrored into state.
  // Changing the key remounts the input with the new default, which is React's
  // own answer to "reset this when that changes" — and avoids the effect-driven
  // state sync that causes cascading renders.
  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault()
        const field = new FormData(event.currentTarget).get(SEARCH_PARAM)
        const trimmed = String(field ?? '').trim()
        navigate(
          trimmed
            ? `/documents?${SEARCH_PARAM}=${encodeURIComponent(trimmed)}`
            : '/documents',
        )
      }}
    >
      <input
        key={applied}
        name={SEARCH_PARAM}
        type="search"
        aria-label="Search documents"
        placeholder="Name or ID, e.g. dodd-5000-01"
        defaultValue={applied}
      />
      <button type="submit">Search</button>
    </form>
  )
}

function NoSuchScreen() {
  const { pathname } = useLocation()
  return (
    <div role="status" className="view">
      <p>
        <strong>There is no screen at {pathname}.</strong>
      </p>
      <p>
        The app is running — this address does not name one of its screens. Pick one
        from the navigation above, or <Link to="/">start at the graph</Link>.
      </p>
    </div>
  )
}

export default function App() {
  // `getHealth` was the last client function with no caller. Every screen reported
  // its own fetch failure, so a backend that was down looked like five unrelated
  // broken screens rather than one cause — which is the class of thing ADR-019 says
  // the app must not misrepresent about its own state. Checked once at mount: this
  // answers "is anything there at all", not "is it there right now".
  const [reachable, setReachable] = useState(true)
  const { pathname, search } = useLocation()

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then(() => {
        if (!cancelled) setReachable(true)
      })
      .catch((cause: unknown) => {
        // Below 500 the backend answered for itself, and the banner would be
        // wrong: a 4xx is a bad request or a bad token, which the screen that
        // made the call reports far better than "check that the stack is up".
        //
        // 5xx stays an outage, and this is the correction to a first attempt
        // that treated every `ApiError` as proof of life. It is not: the dev
        // proxy registers no error handler (`vite.config.ts`), so when the
        // backend container is down Vite's default turns ECONNREFUSED into a
        // plain 500, `request()` wraps that as `ApiError(500)`, and suppressing
        // on it hid the banner during exactly the outage it exists to report.
        //
        // `/health` also carries no auth (`routers/admin.py`), so the wrong-token
        // case the first attempt was written for cannot arise on this route at
        // all — the 4xx worth keeping quiet about here is a future one.
        const answeredForItself = cause instanceof ApiError && cause.status < 500
        if (!cancelled) setReachable(answeredForItself)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      {/* First in the DOM so it is the first tab stop. Without it a keyboard
          reader paid ten header stops on every navigation, and /documents put
          618 focusable elements in front of them with nothing to jump past. */}
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      {!reachable && (
        <div role="alert">
          The backend is not answering. Every screen below will fail to load until it
          does — this is one cause, not several. Check that the stack is up.
        </div>
      )}
      <nav aria-label="Main" className="app-nav">
        <ul>
          {ROUTES.map((route) => (
            <li key={route.to}>
              {/* NavLink sets aria-current="page" on the active route itself. */}
              <NavLink to={route.to} end={route.to === '/'}>
                {route.label}
              </NavLink>
            </li>
          ))}
        </ul>
        {/* STORY-014, an MVP bar: "Users can search by document name or ID".
            Beside the navigation rather than on a screen, because the bar asks for
            reach from anywhere — and submitting to the Documents table rather than
            a results view of its own, because a separate view would duplicate the
            table's cap-and-say-so behaviour (STORY-070) and its row rendering to
            show the same rows. */}
        <SearchDocuments />
      </nav>

      {/* Every screen's content lives here. Before this there was no `main` at
          all: axe reported `landmark-one-main` and `region` on all nine screens,
          and on /documents the region violation covered 624 nodes — the whole
          page outside any landmark. On the graph screen the only `h1` sat inside
          an `aside`, so the page title was in a complementary landmark and the
          content was in none. */}
      <main id="main">
        {/* `resetKey`, not `key`: leaving a screen that threw clears the
            failure, while the subtree keeps its identity so navigating between
            two documents does not remount DocumentDetail and re-run its
            corpus-wide fetch. `search` is included because a crash on
            /documents?q=X must clear when the reader types a new term — the path
            alone does not change there. */}
        <ErrorBoundary resetKey={`${pathname}${search}`}>
          <Routes>
            {ROUTES.map((route) => (
              <Route key={route.to} path={route.to} element={route.element} />
            ))}
            {/* Not in ROUTES: ROUTES is the navigation, and App.test.tsx asserts
                one link per entry. A document's detail page is reached from its
                row, not from a nav item that would need a document to point at. */}
            <Route path="/documents/:slug" element={<DocumentDetail />} />
            {/* Anything else. Without this, a mistyped or stale URL matched no
                route and React Router rendered nothing at all: the navigation bar
                over an empty page, which is the blank-that-reads-as-broken
                ADR-019 exists to forbid — and worse here, because the reader has
                no reason to suspect the address rather than the app. */}
            <Route path="*" element={<NoSuchScreen />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </>
  )
}
