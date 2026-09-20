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

import GraphExplorer, {
  LINK_DISTANCE,
  MIN_MARK_SCALE,
  NODE_RELATIVE_SIZE,
} from './GraphExplorer'

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
  // Ordered, because the marks are told apart by the sequence of operations
  // that draws them — an arc then a fill is a disc, an arc then a stroke is a
  // ring, and asserting only that `arc` was called cannot tell those apart.
  const ops: { op: string; args: number[]; style?: string; width?: number }[] = []
  const context = {} as { strokeStyle: string; fillStyle: string; lineWidth: number }
  // Styles are captured at the moment the mark is committed, not merely exposed
  // as inert properties. Without this a mark stroked in a transparent colour, or
  // at zero width, leaves every recorded operation identical while painting
  // nothing at all — the suite would stay green over a blank canvas.
  const record = (op: string) => vi.fn((...args: unknown[]) => {
    const committed = op === 'stroke' || op === 'fill'
    ops.push({
      op,
      args: args.filter((a) => typeof a === 'number') as number[],
      ...(committed
        ? {
            style: op === 'fill' ? context.fillStyle : context.strokeStyle,
            width: context.lineWidth,
          }
        : {}),
    })
  })
  Object.assign(context, {
    ops,
    fillText: vi.fn(),
    strokeText: vi.fn(),
    measureText: vi.fn(() => ({ width: 40 })),
    beginPath: record('beginPath'),
    moveTo: record('moveTo'),
    lineTo: record('lineTo'),
    arc: record('arc'),
    closePath: record('closePath'),
    stroke: record('stroke'),
    fill: record('fill'),
    font: '',
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 0,
    lineJoin: '',
    textAlign: '',
    textBaseline: '',
  })
  return context as typeof context & {
    ops: typeof ops
    fillText: ReturnType<typeof vi.fn>
    strokeText: ReturnType<typeof vi.fn>
    measureText: ReturnType<typeof vi.fn>
    beginPath: ReturnType<typeof vi.fn>
    moveTo: ReturnType<typeof vi.fn>
    lineTo: ReturnType<typeof vi.fn>
    arc: ReturnType<typeof vi.fn>
    closePath: ReturnType<typeof vi.fn>
    stroke: ReturnType<typeof vi.fn>
    fill: ReturnType<typeof vi.fn>
  }
}

type FakeContext = ReturnType<typeof fakeCanvasContext>

/** The marks drawn between one `beginPath` and the next, as a compact shape
 *  string — "moveTo,lineTo,stroke". One painter draws several independent
 *  marks, so a test that looked at the whole op log could not say which mark
 *  it was reading. */
function paths(ctx: FakeContext): string[] {
  const out: string[] = []
  for (const { op } of ctx.ops) {
    if (op === 'beginPath') out.push('')
    else if (out.length) out[out.length - 1] += (out[out.length - 1] ? ',' : '') + op
  }
  return out
}

/** How many separate line segments a path holds — one `moveTo` starts each. */
const segments = (path: string) => path.split(',').filter((op) => op === 'moveTo').length

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

// ---------------------------------------------------------------------------
// U5. How much is known about a document, encoded on the node itself.
//
// Colour and size are already spent on the corpus/external distinction, and
// R11 reserves motion and saturated colour for a later change encoding. What
// is left is shape and position, so the tier is a counted mark and the
// assessment state is a separate one — never a dimmer version of the tier.
// ---------------------------------------------------------------------------

/** A neighbourhood holding one document at each of the five tiers. */
const ladderView: GraphOut = {
  nodes: [
    node('tier-5', 'Reviewed Links', { fidelity_tier: 5 }),
    node('tier-4', 'Obligations Built', { fidelity_tier: 4 }),
    node('tier-3', 'Text Ingested', { fidelity_tier: 3 }),
    node('tier-2', 'In Manifest', {
      fidelity_tier: 2,
      assessment_state: null,
      unresolved_names: null,
    }),
    external('tier-1', 'Cited Only'),
  ],
  edges: [
    { source: 'tier-5', target: 'tier-4' },
    { source: 'tier-5', target: 'tier-3' },
    { source: 'tier-5', target: 'tier-2' },
    { source: 'tier-5', target: 'tier-1' },
  ],
  total_nodes: 5,
  returned_nodes: 5,
  truncated: false,
  truncation_basis: null,
  unread_corpus_documents: 0,
}

const showLadder = async () => {
  getGraph.mockResolvedValue(ladderView)
  showFocused('/?focus=tier-5')
  await waitFor(() => screen.getByTestId('force-graph'))
}

/** Paint one node and return the marks drawn around it.
 *
 *  Painted under the focused node's own id, which sits at the centre of a
 *  neighbourhood drawn whole — so the "may be hiding more" mark stays out of
 *  the way of tests that are about the other two marks. The tests that want it
 *  ask for it by making the response truncated. */
function marksFor(overrides: Partial<GraphNode>, globalScale = 1) {
  const paint = lastProps().nodeCanvasObject as Painter
  const ctx = fakeCanvasContext()
  paint({ ...node('tier-5', 'X', overrides), x: 0, y: 0 }, ctx, globalScale)
  return { ctx, paths: paths(ctx) }
}

/** Each mark's size and standoff in *screen* pixels at a given zoom.
 *
 *  Four separate conversions, measured separately: the tick's length, its
 *  standoff from the circle, the badge's radius and the badge's standoff are
 *  four places the canvas-unit conversion can be forgotten one at a time, and a
 *  check on any one of them passes while the other three are wrong. */
function inScreenPixels(globalScale: number) {
  const { ctx } = marksFor({ fidelity_tier: 5, assessment_state: 'not_assessed' }, globalScale)
  const ops = firstPathOps(ctx)
  const from = ops.find((o) => o.op === 'moveTo')!.args
  const to = ops.find((o) => o.op === 'lineTo')!.args
  const badge = ctx.ops.find((o) => o.op === 'arc')!
  return {
    tick: Math.hypot(to[0] - from[0], to[1] - from[1]) * globalScale,
    // Standoff from a circle whose own radius is in canvas units and so does
    // genuinely scale with the drawing.
    gap: (Math.hypot(from[0], from[1]) - NODE_RELATIVE_SIZE) * globalScale,
    badge: badge.args[2] * globalScale,
    badgeOffset:
      (Math.hypot(badge.args[0], badge.args[1]) - NODE_RELATIVE_SIZE) * globalScale,
  }
}

/** How far the furthest painted point sits from the node centre.
 *
 *  An `arc` op's recorded args are its *centre*, so its own radius has to be
 *  added or every circular mark is measured short by its own size — which is
 *  exactly the error that let a mark escape the hit area. */
function reachOf(ctx: FakeContext, cx: number, cy: number): number {
  return Math.max(
    ...ctx.ops
      .filter((o) => o.op === 'moveTo' || o.op === 'lineTo' || o.op === 'arc')
      .map((o) => Math.hypot(o.args[0] - cx, o.args[1] - cy) + (o.op === 'arc' ? o.args[2] : 0)),
  )
}

/** The operations of the first mark alone — the tier ticks. */
function firstPathOps(ctx: FakeContext) {
  const start = ctx.ops.findIndex((o) => o.op === 'beginPath')
  const end = ctx.ops.findIndex((o, i) => i > start && o.op === 'beginPath')
  return ctx.ops.slice(start + 1, end === -1 ? undefined : end)
}

describe('GraphExplorer — the fidelity tier on the node', () => {
  it('draws one mark per tier, so the count is the ordinal itself', async () => {
    // KTD4: shape carries no inherent order, so the ordinal is one repeated
    // form counted — not five different badges, and not a hue ramp.
    await showLadder()

    for (const tier of [1, 2, 3, 4, 5] as const) {
      const { paths: drawn } = marksFor({ fidelity_tier: tier, assessment_state: null })
      const tierPath = drawn[0]
      expect(segments(tierPath)).toBe(tier)
    }
  })

  it('separates each tier from the one below by extent, not only by count', async () => {
    // Counting five small ticks fails at the size nodes actually render. The
    // ticks are laid out on a fixed angular pitch from a fixed start, so the
    // arc they span grows with the tier and stays readable when the individual
    // ticks no longer are.
    await showLadder()

    const spanOf = (tier: 1 | 2 | 3 | 4 | 5) => {
      const { ctx } = marksFor({ fidelity_tier: tier, assessment_state: null })
      const ends = firstPathOps(ctx).filter((o) => o.op === 'moveTo').map((o) => o.args)
      const angles = ends.map(([x, y]) => Math.atan2(y, x))
      return Math.max(...angles) - Math.min(...angles)
    }

    const spans = ([1, 2, 3, 4, 5] as const).map(spanOf)
    for (let i = 1; i < spans.length; i += 1) {
      expect(spans[i]).toBeGreaterThan(spans[i - 1])
    }
  })

  it('distinguishes a cited-only neighbour from an ingested one without colour', async () => {
    // AE4. The two already differ in fill and radius, and a reader who can
    // separate neither is exactly the reader this mark is for.
    await showLadder()

    const citedOnly = marksFor({ fidelity_tier: 1, is_external: true, assessment_state: null })
    const ingested = marksFor({ fidelity_tier: 3 })

    expect(segments(citedOnly.paths[0])).not.toBe(segments(ingested.paths[0]))
  })
})

describe('GraphExplorer — the assessment state on the node', () => {
  it('distinguishes references never read from a document confirmed to cite nothing', async () => {
    // AE2, and the reason the axis exists at all. Both documents draw no
    // outgoing edge; only the mark says whether that is a finding or a gap.
    await showLadder()

    const unread = marksFor({ fidelity_tier: 3, assessment_state: 'not_assessed' })
    const citesNothing = marksFor({
      fidelity_tier: 3,
      assessment_state: 'assessed_cites_nothing',
    })

    expect(unread.paths[1]).not.toBe(citesNothing.paths[1])
  })

  it('draws a different silhouette for every one of the four states', async () => {
    // Two of the four were reachable only through a panel-text fixture, so the
    // triangle's point order and the boolean that turns the shared arc into a
    // filled disc rather than a hollow ring were both unguarded: pinning that
    // boolean to a constant left the whole suite green. Compared as a set,
    // because "distinct" is a property of the four together, not of any pair.
    await showLadder()

    const silhouettes = (
      ['not_assessed', 'assessed_cites_nothing', 'assessed_names_unresolved', 'assessed_all_resolved'] as const
    ).map((assessment_state) => marksFor({ fidelity_tier: 5, assessment_state }).paths[1])

    expect(new Set(silhouettes).size).toBe(4)
  })

  it('fills the disc for a section read clean and leaves the ring open for one never read', async () => {
    // These two share their geometry and differ only in the last operation, so
    // the set comparison above is the only thing that separates them and this
    // names what the difference has to be. A hollow ring reads as "nothing is
    // known here"; painting it over a document whose references all resolved
    // reports the one state as the other.
    await showLadder()

    expect(marksFor({ fidelity_tier: 5, assessment_state: 'assessed_all_resolved' }).paths[1])
      .toMatch(/arc,.*fill$/)
    expect(marksFor({ fidelity_tier: 5, assessment_state: 'not_assessed' }).paths[1])
      .toMatch(/arc,.*stroke$/)
  })

  it('closes the triangle for names the corpus could not resolve', async () => {
    // An unclosed path leaves the caution shape reading as a bare chevron.
    await showLadder()

    const { paths: drawn } = marksFor({
      fidelity_tier: 5,
      assessment_state: 'assessed_names_unresolved',
    })
    expect(drawn[1]).toContain('closePath')
    expect(segments(drawn[1])).toBe(1)
  })

  it('draws the tier and the assessment state as two marks, not one blended one', async () => {
    // The axes are independent — a document at the top of the ladder whose
    // references were never located is a real state. Folding the second into
    // the first (a dimmer tier mark, a shorter arc) would make it unreadable.
    await showLadder()

    const { ctx, paths: drawn } = marksFor({
      fidelity_tier: 4,
      assessment_state: 'not_assessed',
    })

    expect(drawn.length).toBeGreaterThanOrEqual(2)
    // Two marks in different places: one mark drawn twice is not two facts.
    const anchors = ctx.ops
      .filter((o) => o.op === 'moveTo' || o.op === 'arc')
      .map((o) => `${Math.round(o.args[0])},${Math.round(o.args[1])}`)
    expect(new Set(anchors).size).toBeGreaterThan(1)
  })

  it('draws no assessment mark below the tier where the axis carries information', async () => {
    // Null below the third tier: there the tier already says nothing has been
    // read, and a second mark repeating it would sit on almost every node in
    // the corpus while separating none of them.
    await showLadder()

    const lowest = marksFor({ fidelity_tier: 1, is_external: true, assessment_state: null })
    expect(lowest.paths).toHaveLength(1)
    expect(segments(lowest.paths[0])).toBe(1)
  })
})

describe('GraphExplorer — what the map does not know it is missing', () => {
  it('marks a node whose neighbours were cut distinctly from one with none left', async () => {
    // AE6. The omission must never render like a document having no further
    // references — that is the same empty answer with two opposite meanings.
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: 'corpus documents before external ones, then by degree',
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    const paint = lastProps().nodeCanvasObject as Painter
    const cut = fakeCanvasContext()
    paint({ ...ladderView.nodes[0], x: 0, y: 0 }, cut, 1)

    getGraph.mockResolvedValue(ladderView)
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getAllByTestId('force-graph'))
    const whole = fakeCanvasContext()
    ;(lastProps().nodeCanvasObject as Painter)({ ...ladderView.nodes[0], x: 0, y: 0 }, whole, 1)

    expect(paths(cut).length).toBeGreaterThan(paths(whole).length)
  })

  it('says the neighbourhood is partial and on what basis it chose', async () => {
    // AE6's other half: a caption that says only "capped" leaves the reader to
    // guess what was dropped.
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: 'corpus documents before external ones, then by degree',
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(
      screen.getByText(/corpus documents before external ones, then by degree/i),
    ).toBeInTheDocument()
  })

  it('qualifies an empty inbound half rather than reporting it as a finding', async () => {
    // AE9. On this corpus almost nothing has had its references read, so
    // "nothing cites this" is mostly a fact about what the system has not done.
    getGraph.mockResolvedValue({ ...ladderView, unread_corpus_documents: 470 })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    const caveat = screen.getByText(/470 corpus documents/i)
    expect(caveat).toHaveTextContent(/never had their own references read/i)
    // What the limitation actually is. These documents are NOT silent: a
    // manifest row names what each one cites even though nobody read the
    // document, so they can and do appear here as citers. Saying they cannot
    // tells the reader to discount inbound edges the graph is drawing.
    expect(caveat).toHaveTextContent(/known only from manifest rows/i)
    expect(caveat).not.toHaveTextContent(/cannot appear/i)
  })

  it('agrees the caveat with its own count', async () => {
    // One document short of fully read rendered "1 corpus documents ... their",
    // against the agreement idiom every other count in this panel uses.
    getGraph.mockResolvedValue({ ...ladderView, unread_corpus_documents: 1 })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    const caveat = screen.getByText(/1 corpus document/i)
    expect(caveat).toHaveTextContent(/1 corpus document has never had its own references read/i)
    expect(caveat).toHaveTextContent(/what it cites is known only from a manifest row/i)
    expect(caveat).not.toHaveTextContent(/documents have/i)
  })

  it('names the render cap itself when the response gives no ordering', async () => {
    // `truncation_basis` is nullable, and the caption's fallback had no test:
    // two fixtures already build truncated:true with a null basis, but both
    // assert a substring that stops before the fallback words.
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: null,
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(screen.getByText(/part of the neighbourhood, chosen by the render cap/i))
      .toBeInTheDocument()
  })

  it('lists no unresolved names when the parse resolved every one', async () => {
    // An empty list and an absent one are different facts here, and only the
    // absent one should draw nothing: `[]` means the parse ran and resolved
    // everything, which is not a list of failures to render.
    getGraph.mockResolvedValue({
      ...ladderView,
      nodes: [node('tier-5', 'Reviewed Links', { fidelity_tier: 5, unresolved_names: [] })],
      edges: [],
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(document.querySelector('.node-unresolved')).toBeNull()
  })

  it('says nothing about an assessment for a document below the axis', async () => {
    // The mirror of the canvas rule, in words: below the third tier
    // `assessment_state` is null because the tier already says nothing was
    // read, and a row that added assessment wording anyway would report a state
    // the API never sent.
    await showLadder()
    const list = screen.getByRole('group', { name: /documents in the graph/i })
    const row = within(list)
      .getByRole('button', { name: /In Manifest/i })
      .closest('li')!

    expect(row).toHaveTextContent(/in the manifest/i)
    expect(row).not.toHaveTextContent(/read, and every name resolved/i)
    expect(row).not.toHaveTextContent(/its own references were never read/i)
    expect(row).not.toHaveTextContent(/cites nothing in the corpus/i)
  })

  it('says nothing about unread documents when every one has been read', async () => {
    // The mirror of the above: a caveat printed unconditionally stops being
    // read, and here it would be false.
    await showLadder()
    expect(screen.queryByText(/never had their own references read/i)).not.toBeInTheDocument()
  })
})

describe('GraphExplorer — the same facts in words', () => {
  it('names each of the five tiers in the keyboard list', async () => {
    // The canvas has no accessible surface of its own, so every mark painted
    // on it has to be a sentence here or it reaches nobody using a reader.
    await showLadder()
    const list = screen.getByRole('group', { name: /documents in the graph/i })

    // Read off the row for the document at that tier, rather than searching the
    // whole list: the tier words share vocabulary with each other on purpose
    // ("text ingested" against "its text has not been ingested"), and a loose
    // search would pass while the words sat on the wrong document.
    const rowFor = (label: string) =>
      within(list)
        .getByRole('button', { name: new RegExp(label, 'i') })
        .closest('li')!

    for (const [label, words] of [
      ['Cited Only', /cited by another document only/i],
      ['In Manifest', /in the manifest/i],
      ['Text Ingested', /— text ingested/i],
      ['Obligations Built', /obligations built/i],
      ['Reviewed Links', /links reviewed/i],
    ] as const) {
      expect(rowFor(label)).toHaveTextContent(words)
    }
  })

  it('names the assessment state in words too, not only as a mark', async () => {
    getGraph.mockResolvedValue({
      ...ladderView,
      nodes: [
        node('tier-5', 'Reviewed Links', { fidelity_tier: 5, assessment_state: 'not_assessed', unresolved_names: null }),
        node('cites-nothing', 'Cites Nothing', { fidelity_tier: 3, assessment_state: 'assessed_cites_nothing' }),
      ],
      edges: [{ source: 'tier-5', target: 'cites-nothing' }],
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))
    const list = within(screen.getByRole('group', { name: /documents in the graph/i }))

    expect(list.getByText(/its own references were never read/i)).toBeInTheDocument()
    expect(list.getByText(/cites nothing in the corpus/i)).toBeInTheDocument()
  })

  it('exposes the reference names the corpus could not resolve', async () => {
    // R7. The names, not a count: an unresolved public law is a different
    // thing from an unresolved DoD issuance the corpus should be holding.
    getGraph.mockResolvedValue({
      ...ladderView,
      nodes: [
        node('tier-5', 'Reviewed Links', {
          fidelity_tier: 5,
          assessment_state: 'assessed_names_unresolved',
          unresolved_names: ['Public Law 116-92', 'An entry nobody could parse'],
        }),
      ],
      edges: [],
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(screen.getByText(/An entry nobody could parse/)).toBeInTheDocument()
    expect(screen.getByText(/Public Law 116-92/)).toBeInTheDocument()
  })

  it('treats the edge of the walk as unknown, not as a document with nothing left', async () => {
    // The boundary the whole mark turns on, and the only input that can see it:
    // nothing was truncated, so the *only* reason a node's neighbourhood is
    // incomplete is that the walk stopped at it. At depth 1 the focused
    // document's own references were all fetched, while its neighbours' were
    // never asked for — so an unmarked neighbour would be claiming a complete
    // reference list the request never went looking for.
    await showLadder()
    const list = screen.getByRole('group', { name: /documents in the graph/i })
    const rowFor = (label: string) =>
      within(list).getByRole('button', { name: new RegExp(label, 'i') }).closest('li')!

    expect(rowFor('Reviewed Links')).not.toHaveTextContent(/may cite more than is drawn/i)
    expect(rowFor('Text Ingested')).toHaveTextContent(/may cite more than is drawn/i)
  })

  it('holds the partial mark while a deeper walk is still in flight', async () => {
    // The window the whole predicate turns on. `expand` advances the depth in
    // the URL synchronously, but the drawing underneath is still the shallower
    // response — in which these documents' own references were never fetched.
    // Clearing the mark on the requested depth rather than the drawn one makes
    // the view assert, for the length of the request, a complete neighbourhood
    // nobody had looked for: a missing mark standing for a known-empty, which
    // is the one reading R10 forbids.
    await showLadder()
    const list = () => screen.getByRole('group', { name: /documents in the graph/i })
    const rowFor = (label: string) =>
      within(list()).getByRole('button', { name: new RegExp(label, 'i') }).closest('li')!

    expect(rowFor('Text Ingested')).toHaveTextContent(/may cite more than is drawn/i)

    let release: (value: GraphOut) => void = () => {}
    getGraph.mockImplementationOnce(
      () => new Promise<GraphOut>((resolve) => { release = resolve }),
    )
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))

    // Depth has moved; the drawing has not. The mark stays.
    expect(rowFor('Text Ingested')).toHaveTextContent(/may cite more than is drawn/i)

    release({
      ...ladderView,
      edges: [...ladderView.edges, { source: 'tier-3', target: 'tier-2' }],
    })
    await waitFor(() =>
      expect(rowFor('Text Ingested')).not.toHaveTextContent(/may cite more than is drawn/i),
    )
  })

  it('stops calling a node partial once the walk has gone past it', async () => {
    // The other side of the same boundary. Expanding to depth 2 walks the
    // neighbours' own references, so what was unknown a moment ago is now
    // drawn — and the mark has to clear, or it degrades into decoration that
    // says "partial" about everything forever.
    await showLadder()
    await userEvent.click(screen.getByRole('button', { name: /expand/i }))
    await waitFor(() => expect(getGraph).toHaveBeenCalledTimes(2))

    const list = screen.getByRole('group', { name: /documents in the graph/i })
    const row = within(list)
      .getByRole('button', { name: /Text Ingested/i })
      .closest('li')!
    expect(row).not.toHaveTextContent(/may cite more than is drawn/i)
  })

  it('marks the focused document too when the budget cut something', async () => {
    // The focus is not exempt. When the render cap dropped nodes, the ones it
    // dropped could be the focus's own neighbours — so the document the map is
    // drawn around is exactly as unable to claim a complete reference list as
    // any other. Asserted on the focus's own row: the sibling test counts
    // matches across the whole list and passes whether or not this one is
    // among them.
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: 'corpus documents before external ones, then by degree',
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    const row = within(screen.getByRole('group', { name: /documents in the graph/i }))
      .getByRole('button', { name: /Reviewed Links/i })
      .closest('li')!
    expect(row).toHaveTextContent(/focused/i)
    expect(row).toHaveTextContent(/may cite more than is drawn/i)
  })

  it('says in words when a node may cite more than is drawn', async () => {
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: 'corpus documents before external ones, then by degree',
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))
    const list = within(screen.getByRole('group', { name: /documents in the graph/i }))

    expect(list.getAllByText(/may cite more than is drawn/i).length).toBeGreaterThan(0)
  })
})

describe('GraphExplorer — the marks do not break the canvas', () => {
  it('keeps a click on a node with marks on that node, not a neighbour', async () => {
    // The marks sit outside the circle the library sizes its hit area from, so
    // the hit area has to grow with them — but only to cover this node's own
    // marks. A region that spread further would swallow the neighbour.
    await showLadder()

    const area = lastProps().nodePointerAreaPaint as (
      node: unknown, colour: string, ctx: unknown, scale: number,
    ) => void
    const ctx = fakeCanvasContext()
    area({ ...ladderView.nodes[0], assessment_state: 'assessed_names_unresolved', x: 40, y: 70 },
      '#ff0000', ctx, 1)

    const circle = ctx.ops.find((o) => o.op === 'arc')!
    expect(circle.args[0]).toBe(40)
    expect(circle.args[1]).toBe(70)

    // Measured against what the painter actually draws, not against a bound
    // both a right and a wrong radius would satisfy: paint the same node and
    // find the furthest point any mark reaches.
    // Painted with the triangle badge, the widest of the four silhouettes: a
    // measurement taken against a round badge cannot see a corner reaching past
    // it. (The ticks still reach furthest today, so this is what keeps the
    // measurement honest if that ever stops being true.)
    const marked = { ...ladderView.nodes[0], assessment_state: 'assessed_names_unresolved' as const }
    const drawn = fakeCanvasContext()
    ;(lastProps().nodeCanvasObject as Painter)({ ...marked, x: 40, y: 70 }, drawn, 1)
    const furthest = reachOf(drawn, 40, 70)
    // Epsilon only for the trig rounding that puts the tick tip 5e-15 past the
    // radius it was computed from; the mutation this guards misses by 1.3.
    expect(circle.args[2]).toBeGreaterThanOrEqual(furthest - 1e-9)
    expect(circle.args[2]).toBeGreaterThan(NODE_RELATIVE_SIZE)
    // And far short of what the layout puts between two linked nodes, or the
    // region would start swallowing the neighbour.
    expect(circle.args[2]).toBeLessThan(LINK_DISTANCE / 2)
  })

  it('never lets a mark shrink below the size it has at 1:1, however far out', async () => {
    // The zoom that suppresses external labels is the view the tier is needed
    // in most — it is the one with no names left on it — and marks in plain
    // canvas units vanish there. Zoomed in they still grow with the node, which
    // is the other half of the same property and the next test.
    await showLadder()

    const reference = inScreenPixels(1)
    for (const globalScale of [0.5, MIN_MARK_SCALE]) {
      const measured = inScreenPixels(globalScale)
      expect(measured.tick).toBeCloseTo(reference.tick, 6)
      expect(measured.gap).toBeCloseTo(reference.gap, 6)
      expect(measured.badge).toBeCloseTo(reference.badge, 6)
      expect(measured.badgeOffset).toBeCloseTo(reference.badgeOffset, 6)
    }
  })

  it('stops holding that size below the floor rather than swallowing a neighbour', async () => {
    // The floor is where the screen-size guarantee stops being worth its cost.
    // Unbounded, the conversion takes a mark — and the hit area sized from it —
    // past the distance the layout puts between two linked nodes, so a click
    // resolves to the wrong document. Below the floor the marks shrink with the
    // canvas again, where neighbouring marks already overlapped anyway.
    await showLadder()

    const reference = inScreenPixels(1)
    expect(inScreenPixels(0.2).tick).toBeLessThan(reference.tick)
  })

  it('keeps the clickable region clear of the neighbour at every zoom', async () => {
    // The bound the region's own comment claims, asserted where it can actually
    // fail. At zoom 1 it passes whatever the conversion does; it was the zooms
    // below that put a linked neighbour's centre inside this node's region.
    await showLadder()

    const area = lastProps().nodePointerAreaPaint as (
      n: unknown, c: string, x: unknown, s: number,
    ) => void
    for (const globalScale of [1, MIN_MARK_SCALE, 0.15, 0.1, 0.01]) {
      const ctx = fakeCanvasContext()
      area({ ...ladderView.nodes[0], x: 0, y: 0 }, '#ff0000', ctx, globalScale)
      const radius = ctx.ops.find((o) => o.op === 'arc')!.args[2]
      expect(radius).toBeLessThan(LINK_DISTANCE / 2)
    }
  })

  it('lets the marks grow with the node when the reader zooms in on one', async () => {
    // The floor is a floor, not a pin. Held to a fixed screen size the marks
    // stop growing with the circle and read as something stuck to the side of
    // it, which is the opposite failure and just as easy to ship.
    await showLadder()

    const reference = inScreenPixels(1)
    const zoomed = inScreenPixels(4)
    expect(zoomed.tick).toBeCloseTo(reference.tick * 4, 6)
    expect(zoomed.badge).toBeCloseTo(reference.badge * 4, 6)
  })

  it('covers the marks of a node that is hiding something, not just the focused one', async () => {
    // Under truncation every node paints the partial mark, the focus included —
    // the budget dropped something, and the focus's own neighbours could be
    // among it. The sibling check above paints the focus at a depth where it is
    // drawn whole, so it never saw this mark at all: the one that sits furthest
    // out, on a diagonal where a careless offset reaches further still.
    getGraph.mockResolvedValue({
      ...ladderView,
      total_nodes: 40,
      returned_nodes: 5,
      truncated: true,
      truncation_basis: 'corpus documents before external ones, then by degree',
    })
    showFocused('/?focus=tier-5')
    await waitFor(() => screen.getByTestId('force-graph'))

    for (const globalScale of [1, 0.1]) {
      const drawn = fakeCanvasContext()
      ;(lastProps().nodeCanvasObject as Painter)(
        { ...ladderView.nodes[2], assessment_state: 'assessed_names_unresolved', x: 40, y: 70 },
        drawn, globalScale,
      )
      // The partial mark is on this node, or the test is measuring nothing.
      expect(paths(drawn).length).toBeGreaterThanOrEqual(3)

      const area = fakeCanvasContext()
      ;(lastProps().nodePointerAreaPaint as (
        n: unknown, c: string, x: unknown, s: number,
      ) => void)(
        { ...ladderView.nodes[2], assessment_state: 'assessed_names_unresolved', x: 40, y: 70 },
        '#ff0000', area, globalScale,
      )

      const radius = area.ops.find((o) => o.op === 'arc')!.args[2]
      expect(radius).toBeGreaterThanOrEqual(reachOf(drawn, 40, 70) - 1e-9)
    }
  })

  it('tucks the marks in against the smaller radius of an external node', async () => {
    // External nodes are drawn smaller — that size is the second, non-colour
    // channel for the corpus/external distinction. The marks hang off the
    // circle's edge, so a radius that ignored the distinction would leave them
    // floating clear of the small nodes and biting into the large ones.
    await showLadder()

    const reachOfTicks = (is_external: boolean) => {
      const { ctx } = marksFor({ fidelity_tier: 5, assessment_state: null, is_external })
      const from = firstPathOps(ctx).find((o) => o.op === 'moveTo')!.args
      return Math.hypot(from[0], from[1])
    }

    expect(reachOfTicks(true)).toBeLessThan(reachOfTicks(false))
  })

  it('commits every mark in a visible colour at a visible width', async () => {
    // A gate has to exercise the thing it gates. Every other check here reads
    // the shape of the drawing — where the paths go, how many there are — and
    // all of them hold just as well over a canvas painted in transparent ink.
    // MARK_COLOUR carries measured contrast ratios in its own comment; nothing
    // noticed whether it was the colour that actually reached the context.
    await showLadder()

    const { ctx } = marksFor({ fidelity_tier: 5, assessment_state: 'not_assessed' })
    const committed = ctx.ops.filter((o) => o.op === 'stroke' || o.op === 'fill')
    expect(committed.length).toBeGreaterThan(0)

    for (const op of committed) {
      expect(op.style).toMatch(/^#[0-9a-f]{6}$/i)
      // The halo is white on purpose; every other committed mark is the dark
      // measured colour. Neither may be transparent.
      expect(op.style).not.toMatch(/transparent|rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0\s*\)/i)
      if (op.op === 'stroke') expect(op.width).toBeGreaterThan(0)
    }
    // And at least one of them is the colour whose contrast was measured.
    expect(committed.some((o) => o.style?.toLowerCase() === '#0f172a')).toBe(true)
  })

  it('introduces no motion in any node state', async () => {
    // R11 reserves motion for a later change encoding. Painting the same node
    // twice must produce the same drawing — a mark that pulsed, rotated or
    // decayed would differ between two identical calls.
    await showLadder()

    const first = marksFor({ fidelity_tier: 4, assessment_state: 'not_assessed' })
    const second = marksFor({ fidelity_tier: 4, assessment_state: 'not_assessed' })

    expect(second.ctx.ops).toEqual(first.ctx.ops)
  })
})
