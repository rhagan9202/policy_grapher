import { act, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GraphNode, GraphOut } from '../api/types'
import {
  OBSERVED_SIZE,
  observedElements,
  reportResize,
  resetObservedElements,
} from '../setupTests'

const graphProps: Record<string, unknown>[] = []

/** Stands in for the imperative handle react-force-graph exposes on its ref,
 *  through which d3 forces are configured. */
const { forceGraph, chargeForce, linkForce } = vi.hoisted(() => {
  const chargeForce = { strength: vi.fn() }
  const linkForce = { distance: vi.fn() }
  return {
    chargeForce,
    linkForce,
    forceGraph: {
      d3Force: vi.fn((name: string) => (name === 'charge' ? chargeForce : linkForce)),
      d3ReheatSimulation: vi.fn(),
      pauseAnimation: vi.fn(),
      resumeAnimation: vi.fn(),
      centerAt: vi.fn(),
      zoomToFit: vi.fn(),
      zoom: vi.fn(),
    },
  }
})

vi.mock('react-force-graph-2d', () => ({
  default: (props: Record<string, unknown>) => {
    graphProps.push(props)
    const ref = props.ref as { current: unknown } | undefined
    if (ref) ref.current = forceGraph
    const data = props.graphData as { nodes: { id: string; label: string }[] }
    return (
      <div data-testid="force-graph">
        {data.nodes.map((node) => (
          <button key={node.id} onClick={() => (props.onNodeClick as (n: unknown) => void)(node)}>
            {node.label}
          </button>
        ))}
      </div>
    )
  },
}))

/** A click on the drawing. The stand-in above renders the nodes as buttons and
 *  the panel's keyboard list renders the same labels, so a click meant for the
 *  canvas has to say so — otherwise the query matches both and the test cannot
 *  tell which route it exercised. */
const canvas = () => within(screen.getByTestId('force-graph'))

const getGraph = vi.fn()

/** The real `ApiError` carries the HTTP status, which is how the view tells a
 *  focused slug that no longer exists from a request that simply failed.
 *  Hoisted because `vi.mock`'s factory runs above ordinary top-level bindings. */
const { ApiErrorStub } = vi.hoisted(() => ({
  ApiErrorStub: class extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
      this.name = 'ApiError'
    }
  },
}))

vi.mock('../api/client', () => ({
  getGraph: (...args: unknown[]) => getGraph(...args),
  ApiError: ApiErrorStub,
}))

import GraphExplorer from './GraphExplorer'

// EmptyState links to the Ingest screen, so any view that can render it
// needs router context.
// The map only ever draws a focused neighbourhood now, so the shared setup
// mounts one. Tests that are about a focused document specifically use
// `showFocused` below with their own slug.
const showFocused = (entry: string) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <GraphExplorer />
    </MemoryRouter>,
  )

const FOCUS = 'dodd-5000-01'
const showGraphExplorer = () => showFocused(`/?focus=${FOCUS}`)

/**
 * A graph node fixture. Every node the API returns carries a tier and an
 * assessment state, so the defaults here are real values rather than
 * placeholders — a plainly-read corpus document — and a test that is not about
 * fidelity does not have to restate them.
 */
function node(id: string, label: string, overrides: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    label,
    is_external: false,
    fidelity_tier: 3,
    assessment_state: 'assessed_all_resolved',
    unresolved_names: [],
    ...overrides,
  }
}

/** A cited-only neighbour: lowest tier, and nothing has been read of it. */
function external(id: string, label: string): GraphNode {
  return node(id, label, {
    is_external: true,
    fidelity_tier: 1,
    assessment_state: null,
    unresolved_names: null,
  })
}

const corpusView: GraphOut = {
  nodes: [
    node('dodd-5000-01', 'DoDD 5000.01'),
    node('dodi-3115-14', 'DoDI 3115.14'),
  ],
  edges: [{ source: 'dodd-5000-01', target: 'dodi-3115-14' }],
  total_nodes: 2,
  returned_nodes: 2,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 0,
}

const expandedView: GraphOut = {
  nodes: [
    ...corpusView.nodes,
    external('public-law-116-92', 'Public Law 116-92'),
  ],
  edges: [
    ...corpusView.edges,
    { source: 'dodi-3115-14', target: 'public-law-116-92' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 0,
}

const reciprocalView: GraphOut = {
  nodes: [
    node('a', 'DoDD A'),
    node('b', 'DoDD B'),
    node('c', 'DoDD C'),
  ],
  edges: [
    { source: 'a', target: 'b' },
    { source: 'b', target: 'a' },
    { source: 'a', target: 'c' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 0,
}

/** Minimal stand-in for the 2D canvas context react-force-graph hands the painter. */
function fakeCanvasContext() {
  return {
    fillText: vi.fn(),
    strokeText: vi.fn(),
    measureText: vi.fn(() => ({ width: 40 })),
    font: '',
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    lineJoin: '',
    textAlign: '',
    textBaseline: '',
  }
}

type Painter = (node: unknown, ctx: unknown, globalScale: number) => void

function lastProps() {
  return graphProps[graphProps.length - 1]
}

afterEach(() => {
  graphProps.length = 0
  getGraph.mockReset()
  chargeForce.strength.mockClear()
  forceGraph.centerAt.mockClear()
  forceGraph.zoomToFit.mockClear()
  forceGraph.zoom.mockClear()
  linkForce.distance.mockClear()
  forceGraph.d3Force.mockClear()
  forceGraph.d3ReheatSimulation.mockClear()
})

describe('GraphExplorer', () => {
  it('shows the name and kind of a clicked node', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(canvas().getByRole('button', { name: 'DoDD 5000.01' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('DoDD 5000.01')
    expect(panel).toHaveTextContent('Corpus document')
  })

  it('renders external nodes in a visually distinct colour from corpus nodes', async () => {
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const props = graphProps[graphProps.length - 1]
    const nodeColor = props.nodeColor as (node: { is_external: boolean }) => string

    const corpusColour = nodeColor({ is_external: false })
    const externalColour = nodeColor({ is_external: true })

    expect(corpusColour).not.toEqual(externalColour)
  })

  it('marks an external node as external rather than rendering "null"', async () => {
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(canvas().getByRole('button', { name: 'Public Law 116-92' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('Public Law 116-92')
    expect(panel).toHaveTextContent(/external/i)
    expect(panel.textContent).not.toMatch(/null/i)
  })

  it('reports truncation instead of presenting a partial graph as whole', async () => {
    getGraph.mockResolvedValue({ ...corpusView, total_nodes: 438, returned_nodes: 300, truncated: true })
    showGraphExplorer()

    expect(await screen.findByText(/showing 300 of 438/i)).toBeInTheDocument()
  })

  it('counts the view without claiming it was capped', async () => {
    // The count is now unconditional and only the *cap* is conditional. This
    // test used to assert the opposite — no count at all unless `truncated` —
    // and that is what hid the defect found in the sprint-12 walkthrough: the
    // default view draws corpus documents only, so the API reports
    // `truncated: false` over a graph showing 23 of 436. Nothing had been
    // truncated, by the API's reckoning, and so nothing was said.
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(
      screen.getByText(/showing 2 documents around DoDD 5000\.01/i),
    ).toBeInTheDocument()
    expect(screen.queryByText(/capped/i)).not.toBeInTheDocument()
  })

  it('surfaces a fetch failure', async () => {
    getGraph.mockRejectedValue(new Error('backend down'))
    showGraphExplorer()

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })

  it('paints the document name onto the canvas for a corpus node', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const paint = lastProps().nodeCanvasObject as Painter
    const ctx = fakeCanvasContext()

    paint({ ...corpusView.nodes[0], x: 0, y: 0 }, ctx, 1)

    expect(ctx.fillText).toHaveBeenCalledWith(
      'DoDD 5000.01',
      expect.any(Number),
      expect.any(Number),
    )
  })

  it('labels external nodes only once zoomed past the threshold', async () => {
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const paint = lastProps().nodeCanvasObject as Painter
    const external = { ...expandedView.nodes[2], x: 0, y: 0 }

    const zoomedOut = fakeCanvasContext()
    paint(external, zoomedOut, 1)
    expect(zoomedOut.fillText).not.toHaveBeenCalled()

    const zoomedIn = fakeCanvasContext()
    paint(external, zoomedIn, 4)
    expect(zoomedIn.fillText).toHaveBeenCalledWith(
      'Public Law 116-92',
      expect.any(Number),
      expect.any(Number),
    )
  })

  it('keeps the default node circle by painting labels after it', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    // 'replace' would make us responsible for drawing the circle and the
    // pointer hit area; 'after' keeps both with the library.
    const mode = lastProps().nodeCanvasObjectMode as (node: unknown) => string
    expect(mode(corpusView.nodes[0])).toBe('after')
  })

  it('positions arrowheads at the target end rather than the link midpoint', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    // Left unset, react-force-graph defaults this to 0.5 and stacks every
    // arrowhead in the middle of the canvas.
    expect(lastProps().linkDirectionalArrowRelPos).toBe(1)
  })

  it('curves both edges of a reciprocal pair and leaves one-way edges straight', async () => {
    getGraph.mockResolvedValue(reciprocalView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const curvature = lastProps().linkCurvature as (link: unknown) => number

    expect(curvature({ source: 'a', target: 'b' })).not.toBe(0)
    expect(curvature({ source: 'b', target: 'a' })).not.toBe(0)
    expect(curvature({ source: 'a', target: 'c' })).toBe(0)
  })

  it('strokes a halo behind the label so it stays legible over edges', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const paint = lastProps().nodeCanvasObject as Painter
    const ctx = fakeCanvasContext()

    paint({ ...corpusView.nodes[0], x: 0, y: 0 }, ctx, 1)

    expect(ctx.strokeText).toHaveBeenCalledWith(
      'DoDD 5000.01',
      expect.any(Number),
      expect.any(Number),
    )
  })

  it('spreads the layout wider than the d3 force defaults', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await waitFor(() => expect(chargeForce.strength).toHaveBeenCalled())

    // d3-force defaults: charge strength -30, link distance 30. Anything at or
    // inside those leaves the 72-edge corpus view as cramped as it was.
    const [strength] = chargeForce.strength.mock.calls[0] as [number]
    const [distance] = linkForce.distance.mock.calls[0] as [number]

    expect(strength).toBeLessThan(-30)
    expect(distance).toBeGreaterThan(30)
  })

  it('still identifies reciprocal pairs after the simulation swaps ids for node objects', async () => {
    getGraph.mockResolvedValue(reciprocalView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const curvature = lastProps().linkCurvature as (link: unknown) => number

    // Once the force simulation starts, react-force-graph replaces each
    // endpoint id with the node object itself. Reading `.source` as a string
    // from then on silently returns 0 for every link.
    expect(curvature({ source: { id: 'a' }, target: { id: 'b' } })).not.toBe(0)
    expect(curvature({ source: { id: 'a' }, target: { id: 'c' } })).toBe(0)
  })
})

describe('GraphExplorer layout', () => {
  it('sizes the canvas to its container, not to the window', async () => {
    // STORY-039: ForceGraph2D with no width/height defaults to
    // window.innerWidth/innerHeight, which pushed the 320px detail panel past
    // the right edge at every viewport size measured (1280 to 2560). Selecting
    // a node worked and could not be seen.
    //
    // The measured size itself is asserted, not merely its type. The first
    // version of this test asked whether the props were numbers, which 0 is —
    // so it passed for a year against a container that was never measured at
    // all, and every graph with data in it rendered a 0x0 canvas.
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => expect(graphProps.length).toBeGreaterThan(0))

    await waitFor(() => {
      const latest = graphProps.at(-1)!
      expect(latest.width).toBe(OBSERVED_SIZE.width)
      expect(latest.height).toBe(OBSERVED_SIZE.height)
    })
  })

  it('measures the container the canvas is drawn in, not some other element', async () => {
    // The regression this guards is not "the numbers are wrong" but "nothing
    // was ever measured": the observer used to be set up in a mount effect,
    // which ran while the view was still rendering "Loading the graph…", found
    // a null ref, and — having no dependencies — never ran again.
    resetObservedElements()
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()

    const graph = await screen.findByTestId('force-graph')
    await waitFor(() =>
      expect(observedElements().some((element) => element.contains(graph))).toBe(true),
    )
  })

})

// Blue and grey carry the whole distinction between a document in the corpus and
// one only cited by it, and nothing on screen said so. Expanding a node made it
// worse: external labels are suppressed below EXTERNAL_LABEL_ZOOM, so the click
// the panel invites produced a fan of anonymous grey dots.
describe('GraphExplorer legend', () => {
  it('says what the two colours mean, and why some names are missing', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    const legend = screen.getByRole('list', { name: /legend/i })
    expect(legend).toHaveTextContent(/in the corpus/i)
    expect(legend).toHaveTextContent(/cited but not ingested/i)
    expect(screen.getByText(/zoom in to read/i)).toBeInTheDocument()
  })
})

// The panel named the selected document and stopped. Its detail page — text,
// editions, obligations, everything the graph cannot show — was reachable only
// by going to Documents and finding the same document again by name.
describe('GraphExplorer selection', () => {
  it('links the selected document to its detail page', async () => {
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()

    await waitFor(() => screen.getByTestId('force-graph'))
    await userEvent.click(canvas().getByRole('button', { name: 'DoDD 5000.01' }))

    const link = await screen.findByRole('link', { name: /open DoDD 5000\.01/i })
    expect(link).toHaveAttribute('href', '/documents/dodd-5000-01')
  })

  it('links an external document too, since it has a page of its own', async () => {
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()

    await waitFor(() => screen.getByTestId('force-graph'))
    await userEvent.click(canvas().getByRole('button', { name: 'Public Law 116-92' }))

    const link = await screen.findByRole('link', { name: /open Public Law 116-92/i })
    expect(link).toHaveAttribute('href', '/documents/public-law-116-92')
  })
})

/** Section 508 is a procurement gate for a federal customer, not a nicety, and
 *  the graph is the screen a demo opens with. Audited before these tests
 *  existed, the canvas rendered as `<canvas width height>` with no role, no
 *  label, no tabindex and no fallback: absent from the accessibility tree and
 *  absent from the tab order, while the panel beside it said "Click a document
 *  to see its details" — an instruction a keyboard user cannot follow. */
describe('GraphExplorer without a mouse', () => {
  it('gives the drawing a text alternative that says what it holds', async () => {
    getGraph.mockResolvedValue(corpusView)

    showGraphExplorer()

    const drawing = await screen.findByRole('img')
    // Not "graph": the name has to carry what is on it, because for a
    // screen-reader user this sentence *is* the picture.
    expect(drawing).toHaveAccessibleName(/2 documents/i)
    expect(drawing).toHaveAccessibleName(/1 reference/i)
  })

  it('reaches every document in the drawing without a mouse', async () => {
    getGraph.mockResolvedValue(corpusView)

    showGraphExplorer()

    // Scoped: the canvas stand-in in this file also renders buttons, and a bare
    // getByRole would pass on those without the real list existing at all.
    const list = await screen.findByRole('group', { name: /documents in the graph/i })
    const buttons = within(list).getAllByRole('button')
    // The focused node's button also says "focused", so match on the label
    // rather than the whole string.
    expect(buttons.map((b) => b.textContent)).toEqual(
      expect.arrayContaining([
        expect.stringContaining('DoDD 5000.01'),
        expect.stringContaining('DoDI 3115.14'),
      ]),
    )

    await userEvent.click(within(list).getByRole('button', { name: 'DoDI 3115.14' }))

    // The same selection a click on the canvas makes, so the detail panel and
    // its "Open …" link are reachable by keyboard too.
    expect(await screen.findByTestId('node-detail')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /open DoDI 3115.14/i }),
    ).toBeInTheDocument()
  })

  it('tells a screen reader the view is capped, as the caption tells everyone else', async () => {
    // The caption warns sighted readers that documents are being withheld. The
    // one sentence a screen-reader user gets did not, so the cap was invisible
    // to exactly the reader who cannot see the drawing thin out.
    getGraph.mockResolvedValue({ ...corpusView, total_nodes: 474, truncated: true })

    showGraphExplorer()

    expect(await screen.findByRole('img')).toHaveAccessibleName(
      /showing 2 of 474/i,
    )
  })

  it('marks external nodes by size as well as colour', async () => {
    // WCAG 1.4.1: colour alone cannot carry the corpus/external distinction, and
    // that distinction is what the drawing exists to show. `nodeColor` has had a
    // test since it was added; the second channel needs one too, or it can be
    // dropped without anything failing.
    getGraph.mockResolvedValue(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    const props = graphProps[graphProps.length - 1]
    const nodeVal = props.nodeVal as (node: { is_external: boolean }) => number

    expect(nodeVal({ is_external: true })).toBeLessThan(
      nodeVal({ is_external: false }),
    )
  })

  it('lets the reader start the layout moving again', async () => {
    // The resume half of the toggle. Only freeze was covered, so a control that
    // froze and then refused to unfreeze would have passed.
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()

    await userEvent.click(await screen.findByRole('button', { name: /freeze layout/i }))
    await userEvent.click(await screen.findByRole('button', { name: /resume layout/i }))

    expect(forceGraph.resumeAnimation).toHaveBeenCalled()
  })

  it('lets the reader stop the layout moving', async () => {
    // WCAG 2.2.2: motion over five seconds needs a way to stop it. Measured
    // before this control existed, the force simulation ran 8.8 to 10.4 seconds
    // on load, and `prefers-reduced-motion` does not reach it — the CSS rule in
    // styles.css cannot govern a canvas simulation.
    getGraph.mockResolvedValue(corpusView)

    showGraphExplorer()

    await userEvent.click(await screen.findByRole('button', { name: /freeze layout/i }))

    expect(forceGraph.pauseAnimation).toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// U4: the map opens on a named document, keeps its layout as it expands, and
// stays usable when a request fails. These assert the focus-first premise
// deliberately rather than adjusting the corpus-first tests above, which state
// a premise R12 removes.
// ---------------------------------------------------------------------------

const focusedView: GraphOut = {
  nodes: [
    node('dodi-3115-14', 'DoDI 3115.14'),
    node('dodd-5143-01', 'DoDD 5143.01'),
    external('public-law-116-92', 'Public Law 116-92'),
  ],
  edges: [
    { source: 'dodi-3115-14', target: 'dodd-5143-01' },
    { source: 'dodi-3115-14', target: 'public-law-116-92' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 19,
}

/** A different document's neighbourhood, sharing no node with `focusedView`.
 *  Disjoint on purpose: the point of the test that uses it is whether the
 *  drawing under a caption belongs to the document the caption names, and two
 *  overlapping fixtures cannot tell those apart. */
const otherFocusedView: GraphOut = {
  nodes: [
    node('dodd-5143-01', 'DoDD 5143.01'),
    node('dodd-5030-19', 'DoDD 5030.19'),
  ],
  edges: [{ source: 'dodd-5143-01', target: 'dodd-5030-19' }],
  total_nodes: 2,
  returned_nodes: 2,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 19,
}

/** Moves the router to another focus. `MemoryRouter` reads `initialEntries`
 *  only on mount, so re-rendering it with a different entry navigates nothing —
 *  the move has to go through the router the view is actually reading. */
function GoTo({ to }: { to: string }) {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(to)}>
      Go to the other document
    </button>
  )
}

/** MemoryRouter keeps its own history rather than the window's, so browser back
 *  is exercised through the router's own navigate(-1). */
function BackButton() {
  const navigate = useNavigate()
  return (
    <button type="button" onClick={() => navigate(-1)}>
      Browser back
    </button>
  )
}

const showFocusedWithHistory = (entry: string) =>
  render(
    <MemoryRouter initialEntries={[entry]}>
      <GraphExplorer />
      <BackButton />
    </MemoryRouter>,
  )

describe('GraphExplorer focused on a document', () => {
  it('opens on the document named in the URL with no interaction', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')

    await waitFor(() => screen.getByTestId('force-graph'))
    expect(getGraph).toHaveBeenCalledWith(
      expect.objectContaining({ focus: 'dodi-3115-14' }),
    )
  })

  it('never asks for the corpus-wide view', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')

    await waitFor(() => screen.getByTestId('force-graph'))
    // R12: the corpus-wide mode stays reachable in the API and unreachable here.
    const options = getGraph.mock.calls[0][0] ?? {}
    expect(options.includeExternal).toBeUndefined()
    expect(options.expand).toBeUndefined()
  })

  it('names which document is focused in the keyboard list', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')

    const list = await screen.findByRole('group', { name: /documents in the graph/i })
    const focused = within(list).getByRole('button', { name: /DoDI 3115\.14/ })
    // Camera centring is a signal only sighted readers get, so the list has to
    // say it in words the same way it says "external".
    expect(focused).toHaveAccessibleName(/focused/i)
    expect(
      within(list).getByRole('button', { name: /DoDD 5143\.01/ }),
    ).not.toHaveAccessibleName(/focused/i)
  })

  it('renders no document focused rather than the corpus when the URL names none', async () => {
    showFocused('/')

    expect(await screen.findByRole('status')).toHaveTextContent(/no document is focused/i)
    // The fallback an implementer reaches for by default is the one R12 removes.
    expect(getGraph).not.toHaveBeenCalled()
    expect(screen.queryByTestId('force-graph')).not.toBeInTheDocument()
  })

  it('offers both existing ways to choose a document', async () => {
    showFocused('/')

    const status = await screen.findByRole('status')
    expect(within(status).getByRole('link', { name: /documents/i })).toHaveAttribute(
      'href',
      '/documents',
    )
    expect(within(status).getByRole('link', { name: /ingest/i })).toHaveAttribute(
      'href',
      '/ingest',
    )
  })

  it('keeps already-drawn nodes at their positions when the neighbourhood grows', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const firstNodes = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
    const drawn = firstNodes.find((n) => n.id === 'dodd-5143-01')!
    ;(drawn as { x?: number; y?: number }).x = 42
    ;(drawn as { x?: number; y?: number }).y = -17

    getGraph.mockResolvedValue({
      ...focusedView,
      nodes: [...focusedView.nodes, node('dodd-5030-19', 'DoDD 5030.19')],
      total_nodes: 4,
      returned_nodes: 4,
    })
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))

    await waitFor(() => {
      const nodes = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
      expect(nodes).toHaveLength(4)
    })
    const after = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
    const same = after.find((n) => n.id === 'dodd-5143-01')!
    // Position survives through object identity, not through matching ids:
    // react-force-graph reheats on every data change and a fresh object has no
    // position to keep.
    expect(same).toBe(drawn)
    expect((same as { x?: number }).x).toBe(42)
  })

  it('seeds a newly revealed node near one already on the canvas', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const before = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
    const revealer = before.find((n) => n.id === 'dodi-3115-14')! as { x?: number; y?: number }
    revealer.x = 100
    revealer.y = 100

    getGraph.mockResolvedValue({
      ...focusedView,
      nodes: [...focusedView.nodes, node('dodd-5030-19', 'DoDD 5030.19')],
      edges: [...focusedView.edges, { source: 'dodi-3115-14', target: 'dodd-5030-19' }],
      total_nodes: 4,
      returned_nodes: 4,
    })
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))

    await waitFor(() => {
      const nodes = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
      expect(nodes).toHaveLength(4)
    })
    const fresh = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes.find(
      (n) => n.id === 'dodd-5030-19',
    )! as { x?: number; y?: number }
    // Dropped at the origin it flies across the canvas as the simulation pulls
    // it home, which is what re-scatters a layout the reader was using.
    expect(fresh.x).toBeCloseTo(100, 0)
    expect(fresh.y).toBeCloseTo(100, 0)
  })

  it('states a focused slug that no longer exists and offers a way onward', async () => {
    getGraph.mockRejectedValue(new ApiErrorStub(404, 'No document with slug.'))
    showFocused('/?focus=gone')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/not found|no longer/i)
    expect(within(alert).getByRole('link', { name: /documents/i })).toBeInTheDocument()
  })

  it('keeps the surface navigable and offers a retry when the request fails', async () => {
    getGraph.mockRejectedValue(new Error('network down'))
    showFocused('/?focus=dodi-3115-14')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/network down/i)
    // An alert that replaces the whole surface strands the reader on a dead page.
    expect(screen.getByRole('heading', { name: /policy grapher/i })).toBeInTheDocument()

    getGraph.mockResolvedValue(focusedView)
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => screen.getByTestId('force-graph'))
  })

  it('keeps the keyboard list in step with the canvas after an expansion', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    getGraph.mockResolvedValue({
      ...focusedView,
      nodes: [...focusedView.nodes, node('dodd-5030-19', 'DoDD 5030.19')],
      total_nodes: 4,
      returned_nodes: 4,
    })
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))

    const list = await screen.findByRole('group', { name: /documents in the graph/i })
    await waitFor(() =>
      expect(within(list).getByRole('button', { name: /DoDD 5030\.19/ })).toBeInTheDocument(),
    )
    expect(within(list).getAllByRole('button')).toHaveLength(4)
  })

  it('centres on the focused node once the layout settles, not on mount', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(forceGraph.centerAt).not.toHaveBeenCalled()

    const props = graphProps.at(-1)!
    const nodes = (props.graphData as { nodes: { id: string; x?: number; y?: number }[] }).nodes
    // Deliberately asymmetric. With an equal spread on both axes the shorter
    // canvas dimension always binds, and the horizontal half of the calculation
    // is unobservable — a fixture that cannot tell the two axes apart cannot
    // guard the choice between them.
    for (const n of nodes) {
      n.x = 307
      n.y = 19
    }
    const focused = nodes.find((n) => n.id === 'dodi-3115-14')!
    focused.x = 7
    focused.y = 9
    ;(props.onEngineStop as () => void)()

    expect(forceGraph.centerAt).toHaveBeenCalledWith(7, 9, expect.any(Number))
    // Zoom computed around the focused node rather than the bounding box, so
    // centring is not immediately undone by a fit. Asserting the value, not
    // merely that it was called: the whole point is which number comes out.
    const [scale] = forceGraph.zoom.mock.calls.at(-1)!
    // The furthest neighbour is 300 away horizontally and 10 vertically, so the
    // horizontal axis is what constrains the zoom here and the vertical one is
    // slack. Fitting the slack axis instead would zoom far past the edge.
    const horizontal = (OBSERVED_SIZE.width / 2 - 60) / 300
    const vertical = (OBSERVED_SIZE.height / 2 - 60) / 10
    expect(horizontal).toBeLessThan(vertical)
    expect(scale).toBeCloseTo(horizontal, 5)
  })

  it('returns to the previously focused document on browser back', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocusedWithHistory('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(
      within(await screen.findByRole('group', { name: /documents in the graph/i }))
        .getByRole('button', { name: /DoDD 5143\.01/ }),
    )
    await userEvent.click(
      await screen.findByRole('button', { name: /draw the map around DoDD 5143\.01/i }),
    )
    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith(
        expect.objectContaining({ focus: 'dodd-5143-01' }),
      ),
    )

    await userEvent.click(screen.getByRole('button', { name: /browser back/i }))

    // Moving focus has to push a history entry, not replace one: browser back
    // is the only way out of a focus change, since the control that used to
    // provide one collapsed to the corpus.
    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith(
        expect.objectContaining({ focus: 'dodi-3115-14' }),
      ),
    )
  })

  it('re-frames for an expansion around the same focused node', async () => {
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const settle = () => (graphProps.at(-1)!.onEngineStop as () => void)()
    const nodes = (graphProps.at(-1)!.graphData as { nodes: { id: string; x?: number; y?: number }[] }).nodes
    nodes.find((n) => n.id === 'dodi-3115-14')!.x = 1
    nodes.find((n) => n.id === 'dodi-3115-14')!.y = 1
    settle()
    expect(forceGraph.centerAt).toHaveBeenCalledTimes(1)
    expect(forceGraph.zoom).toHaveBeenCalledTimes(1)

    // A settle with the same node set is the simulation twitching, not news.
    settle()
    expect(forceGraph.zoom).toHaveBeenCalledTimes(1)

    getGraph.mockResolvedValue({
      ...focusedView,
      nodes: [...focusedView.nodes, node('dodd-5030-19', 'DoDD 5030.19')],
      total_nodes: 4,
      returned_nodes: 4,
    })
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))
    await waitFor(() => {
      const after = (graphProps.at(-1)!.graphData as { nodes: unknown[] }).nodes
      expect(after).toHaveLength(4)
    })
    settle()

    // The new arrivals are outside the old frame, so the view is fitted again —
    // but the camera does not drag back to the focused node, which is where a
    // reader who has panned away would lose their place.
    expect(forceGraph.zoom).toHaveBeenCalledTimes(2)
    // Re-framed for the arrivals, but still around the same focused node.
    expect(forceGraph.centerAt).toHaveBeenCalledTimes(2)
    expect(forceGraph.centerAt.mock.calls[1].slice(0, 2)).toEqual(
      forceGraph.centerAt.mock.calls[0].slice(0, 2),
    )
  })

  it('fits the vertical axis when that is the one that constrains', async () => {
    // The sibling test above spreads the neighbourhood horizontally, so the
    // horizontal term binds there. That alone does not guard the choice: drop
    // the vertical term from the `Math.min` and that test still passes, because
    // the term it dropped was never the smaller one. This is the same
    // measurement with the axes swapped, and it fails under exactly the
    // mutation the other one cannot see — which is the pair, not either test.
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const props = graphProps.at(-1)!
    const nodes = (props.graphData as { nodes: { id: string; x?: number; y?: number }[] }).nodes
    for (const n of nodes) {
      n.x = 19
      n.y = 307
    }
    const focused = nodes.find((n) => n.id === 'dodi-3115-14')!
    focused.x = 9
    focused.y = 7
    ;(props.onEngineStop as () => void)()

    const [scale] = forceGraph.zoom.mock.calls.at(-1)!
    const horizontal = (OBSERVED_SIZE.width / 2 - 60) / 10
    const vertical = (OBSERVED_SIZE.height / 2 - 60) / 300
    expect(vertical).toBeLessThan(horizontal)
    expect(scale).toBeCloseTo(vertical, 5)
  })

  it('re-frames when the canvas is resized, not only when the layout settles', async () => {
    // `onEngineStop` fires once and never again. Anything that invalidates the
    // framing afterwards — a window drag, or the breakpoint where the panel
    // restacks and the canvas loses height — would otherwise leave the
    // neighbourhood framed for a box that no longer exists, with no path back:
    // the only event that would have corrected it has already happened.
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const props = graphProps.at(-1)!
    const nodes = (props.graphData as { nodes: { id: string; x?: number; y?: number }[] }).nodes
    for (const n of nodes) {
      n.x = 307
      n.y = 19
    }
    const focused = nodes.find((n) => n.id === 'dodi-3115-14')!
    focused.x = 7
    focused.y = 9
    ;(props.onEngineStop as () => void)()
    const [settled] = forceGraph.zoom.mock.calls.at(-1)!
    expect(settled).toBeCloseTo((OBSERVED_SIZE.width / 2 - 60) / 300, 5)

    // The observer fires outside React's event system, so the state update it
    // drives has to be wrapped for the effects to flush.
    act(() => reportResize({ width: 400, height: 600 }))

    await waitFor(() => {
      const [resized] = forceGraph.zoom.mock.calls.at(-1)!
      // The narrower canvas has to hold the same 300-unit spread, so the scale
      // drops. Asserting the new value rather than the call count: a re-frame
      // that recomputed against the old width would still have been called.
      expect(resized).toBeCloseTo((400 / 2 - 60) / 300, 5)
    })
    // Still the focused node at the centre, not the bounding box.
    expect(forceGraph.centerAt.mock.calls.at(-1)!.slice(0, 2)).toEqual([7, 9])
  })

  it('never labels one document\u2019s neighbourhood with another\u2019s name', async () => {
    // The caption, the count and the keyboard list are all computed from the
    // slug in the URL, while the drawing under them is whatever arrived last.
    // Hold a response past a focus change and those two disagree — the previous
    // document\u2019s neighbourhood, captioned as the new one\u2019s.
    let release: (value: GraphOut) => void = () => {}
    getGraph.mockImplementation((options: { focus: string }) =>
      options.focus === 'dodi-3115-14'
        ? Promise.resolve(focusedView)
        : new Promise<GraphOut>((resolve) => {
            release = resolve
          }),
    )
    showFocusedWithHistory('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))
    expect(
      (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes.map((n) => n.id),
    ).toContain('dodi-3115-14')

    await userEvent.click(
      within(await screen.findByRole('group', { name: /documents in the graph/i }))
        .getByRole('button', { name: /DoDD 5143\.01/ }),
    )
    await userEvent.click(screen.getByRole('button', { name: /draw the map around/i }))

    // The second request has not answered. Nothing may be drawn under the new
    // name until it does.
    expect(screen.queryByTestId('force-graph')).not.toBeInTheDocument()

    release(otherFocusedView)
    await waitFor(() => screen.getByTestId('force-graph'))
    const drawn = (graphProps.at(-1)!.graphData as { nodes: { id: string }[] }).nodes
    expect(drawn.map((n) => n.id)).toContain('dodd-5143-01')
    expect(drawn.map((n) => n.id)).not.toContain('dodi-3115-14')
  })

  it('does not report one document\u2019s failure against the next one', async () => {
    // A 404 says a named slug does not exist. Left unkeyed it outlives the slug
    // it was about, so moving to a document that does exist reports it missing
    // while its own request is still in flight.
    // The second request is held open on purpose. Once it answers the error is
    // cleared anyway, for a reason that has nothing to do with keying — so an
    // assertion made after it lands passes either way. The only moment the
    // keying is observable is while the new document's request is in flight.
    let release: (value: GraphOut) => void = () => {}
    getGraph.mockImplementation((options: { focus: string }) =>
      options.focus === 'ghost'
        ? Promise.reject(new ApiErrorStub(404, 'No such document'))
        : new Promise<GraphOut>((resolve) => {
            release = resolve
          }),
    )
    render(
      <MemoryRouter initialEntries={['/?focus=ghost']}>
        <GraphExplorer />
        <GoTo to="/?focus=dodi-3115-14" />
      </MemoryRouter>,
    )
    await screen.findByText(/that document was not found/i)

    await userEvent.click(screen.getByRole('button', { name: /go to the other document/i }))

    // Loading, not "that document was not found" — nothing is yet known about
    // this document, and the previous one's 404 is not an answer about it.
    expect(await screen.findByText(/loading the neighbourhood/i)).toBeInTheDocument()
    expect(screen.queryByText(/that document was not found/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    release(focusedView)
    await waitFor(() => screen.getByTestId('force-graph'))
  })

  it('keeps the layout stopped when the canvas is replaced after a retry', async () => {
    // `frozen` is component state, but what it describes is one canvas\u2019s
    // animation loop. A failure unmounts that canvas and a retry mounts a fresh
    // one, animating by default — so without reasserting the flag the motion a
    // reader deliberately stopped restarts under a button still offering to
    // resume it, and the reheat that follows never ticks.
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: /freeze layout/i }))
    expect(forceGraph.pauseAnimation).toHaveBeenCalled()

    getGraph.mockRejectedValueOnce(new Error('network'))
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))
    await waitFor(() => screen.getByRole('button', { name: /retry/i }))
    expect(screen.queryByTestId('force-graph')).not.toBeInTheDocument()

    forceGraph.pauseAnimation.mockClear()
    forceGraph.resumeAnimation.mockClear()
    getGraph.mockResolvedValue(focusedView)
    await userEvent.click(screen.getByRole('button', { name: /retry/i }))
    await waitFor(() => screen.getByTestId('force-graph'))

    // The new instance is paused, and the button still offers to start it.
    expect(forceGraph.pauseAnimation).toHaveBeenCalled()
    expect(forceGraph.resumeAnimation).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /resume layout/i })).toBeInTheDocument()
  })

  it('says the drawing it is holding is being deepened, not that it is final', async () => {
    // An expansion keeps the current drawing on screen while the larger set
    // loads — the caption still describes it truthfully, and the layout the
    // reader was using survives. What is *not* true in that moment is that the
    // view is settled, and a reader who cannot see the canvas has no other cue.
    getGraph.mockResolvedValue(focusedView)
    showFocused('/?focus=dodi-3115-14')
    await waitFor(() => screen.getByTestId('force-graph'))

    const canvas = () => screen.getByRole('img', { name: /dependency map centred on/i })
    expect(canvas()).toHaveAttribute('aria-busy', 'false')

    let release: (value: GraphOut) => void = () => {}
    getGraph.mockImplementationOnce(
      () => new Promise<GraphOut>((resolve) => { release = resolve }),
    )
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))

    // Still the same drawing, and it still says so — but busy.
    expect(screen.getByTestId('force-graph')).toBeInTheDocument()
    expect(canvas()).toHaveAttribute('aria-busy', 'true')

    release({
      ...focusedView,
      nodes: [...focusedView.nodes, node('dodd-5030-19', 'DoDD 5030.19')],
      edges: [...focusedView.edges, { source: 'dodi-3115-14', target: 'dodd-5030-19' }],
      total_nodes: 4,
      returned_nodes: 4,
    })
    await waitFor(() => expect(canvas()).toHaveAttribute('aria-busy', 'false'))
  })

  it('never sends a depth the API will refuse', async () => {
    getGraph.mockResolvedValue(focusedView)
    // These parameters ride in the URL so a view can be shared, so a
    // hand-edited or truncated link is an ordinary way to arrive — and the API
    // types depth as an integer, refusing anything else with a 422.
    showFocused('/?focus=dodi-3115-14&depth=1.5')

    await waitFor(() => screen.getByTestId('force-graph'))
    const { depth } = getGraph.mock.calls[0][0]
    expect(Number.isInteger(depth)).toBe(true)
    expect(depth).toBeGreaterThanOrEqual(1)
    expect(depth).toBeLessThanOrEqual(3)
  })
})
