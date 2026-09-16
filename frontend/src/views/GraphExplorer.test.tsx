import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GraphOut } from '../api/types'
import { OBSERVED_SIZE, observedElements, resetObservedElements } from '../setupTests'

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
vi.mock('../api/client', () => ({
  getGraph: (...args: unknown[]) => getGraph(...args),
  ApiError: class extends Error {},
}))

import GraphExplorer from './GraphExplorer'

// EmptyState links to the Ingest screen, so any view that can render it
// needs router context.
const showGraphExplorer = () =>
  render(
    <MemoryRouter>
      <GraphExplorer />
    </MemoryRouter>,
  )

const corpusView: GraphOut = {
  nodes: [
    { id: 'dodd-5000-01', label: 'DoDD 5000.01', is_external: false },
    { id: 'dodi-3115-14', label: 'DoDI 3115.14', is_external: false },
  ],
  edges: [{ source: 'dodd-5000-01', target: 'dodi-3115-14' }],
  total_nodes: 2,
  returned_nodes: 2,
  truncated: false,
}

const expandedView: GraphOut = {
  nodes: [
    ...corpusView.nodes,
    { id: 'public-law-116-92', label: 'Public Law 116-92', is_external: true },
  ],
  edges: [
    ...corpusView.edges,
    { source: 'dodi-3115-14', target: 'public-law-116-92' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
}

const reciprocalView: GraphOut = {
  nodes: [
    { id: 'a', label: 'DoDD A', is_external: false },
    { id: 'b', label: 'DoDD B', is_external: false },
    { id: 'c', label: 'DoDD C', is_external: false },
  ],
  edges: [
    { source: 'a', target: 'b' },
    { source: 'b', target: 'a' },
    { source: 'a', target: 'c' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
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
  linkForce.distance.mockClear()
  forceGraph.d3Force.mockClear()
  forceGraph.d3ReheatSimulation.mockClear()
})

describe('GraphExplorer', () => {
  it('fetches and renders the default corpus view on mount', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()

    await waitFor(() => expect(screen.getByTestId('force-graph')).toBeInTheDocument())
    expect(getGraph).toHaveBeenCalledWith({})
    expect(canvas().getByText('DoDD 5000.01')).toBeInTheDocument()
  })

  it('shows the name and kind of a clicked node', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(canvas().getByRole('button', { name: 'DoDD 5000.01' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('DoDD 5000.01')
    expect(panel).toHaveTextContent('Corpus document')
  })

  it('refetches with expand when a node is clicked', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValueOnce(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(canvas().getByRole('button', { name: 'DoDI 3115.14' }))

    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({ expand: 'dodi-3115-14' }),
    )
    await waitFor(() => expect(canvas().getByText('Public Law 116-92')).toBeInTheDocument())
  })

  it('stops saying externals are hidden once an expansion has pulled them in', async () => {
    // The caption was gated on the toggle alone. Clicking a corpus node pulls
    // that document's external references onto the canvas, so the panel read
    // "Showing 40 documents in the corpus. Documents cited but never ingested
    // are hidden." over a picture in which 17 of the 40 were exactly those
    // documents — the sentence contradicting the drawing at the single most
    // natural demo gesture.
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValueOnce(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(canvas().getByRole('button', { name: 'DoDI 3115.14' }))
    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({ expand: 'dodi-3115-14' }),
    )

    const count = await screen.findByText(/showing 3 documents/i)
    expect(count.textContent).not.toMatch(/hidden/i)
    // And it names what arrived, rather than leaving unlabelled grey dots.
    expect(count.textContent).toMatch(/1 (of them is|cited)/i)
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

    expect(screen.getByText(/showing 2 documents in the corpus/i)).toBeInTheDocument()
    expect(screen.getByText(/cited but never ingested are hidden/i)).toBeInTheDocument()
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

  it('says the corpus is empty rather than drawing an empty canvas', async () => {
    getGraph.mockResolvedValue({
      nodes: [],
      edges: [],
      total_nodes: 0,
      returned_nodes: 0,
      truncated: false,
    })
    showGraphExplorer()

    expect(await screen.findByRole('status')).toHaveTextContent(
      /no documents have been ingested yet/i,
    )
  })
})

// Found in the sprint-12 walkthrough, against the real corpus. `GET /graph`
// answers with corpus documents only unless asked otherwise, so the opening
// screen drew 23 nodes over a graph of 436 — and reported `total_nodes: 23,
// truncated: false`, which is true of what it fetched and silent about what it
// left out. The existing "Showing N of M" line could not fire, because by the
// API's reckoning nothing had been truncated.
//
// `includeExternal` has been in `GraphOptions` since the client was written and
// nothing ever passed it. The only way to see an external document was to click
// a corpus node and expand it, one at a time.
describe('GraphExplorer including external references', () => {
  const wholeCorpus: GraphOut = {
    nodes: [
      ...corpusView.nodes,
      { id: 'public-law-116-92', label: 'Public Law 116-92', is_external: true },
    ],
    edges: corpusView.edges,
    total_nodes: 436,
    returned_nodes: 300,
    truncated: true,
  }

  it('fetches corpus documents alone to begin with', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    expect(getGraph).toHaveBeenLastCalledWith({})
  })

  it('asks for external references when the reader turns them on', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValue(wholeCorpus)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    await userEvent.click(
      screen.getByRole('checkbox', { name: /include external references/i }),
    )

    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({ includeExternal: true }),
    )
  })

  it('names what the default view leaves out, rather than counting what it kept', async () => {
    // `total_nodes` is scoped to the query, so with external references off the
    // API answers "23 of 23" over a corpus of 436 — a true sentence that hides
    // the omission completely. Naming the exclusion is the only honest form.
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    expect(screen.getByText(/cited but never ingested are hidden/i)).toBeInTheDocument()
  })

  it('counts against the whole corpus once external references are in', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValue(wholeCorpus)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    await userEvent.click(
      screen.getByRole('checkbox', { name: /include external references/i }),
    )

    expect(await screen.findByText(/showing 300 of 436 documents/i)).toBeInTheDocument()
    expect(screen.getByText(/capped/i)).toBeInTheDocument()
  })

  it('keeps the toggle on while a node is expanded', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValue(wholeCorpus)
    showGraphExplorer()
    await screen.findByTestId('force-graph')

    await userEvent.click(
      screen.getByRole('checkbox', { name: /include external references/i }),
    )
    await waitFor(() => expect(getGraph).toHaveBeenLastCalledWith({ includeExternal: true }))

    await waitFor(() => screen.getByTestId('force-graph'))
    await userEvent.click(canvas().getByRole('button', { name: 'DoDI 3115.14' }))

    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({
        expand: 'dodi-3115-14',
        includeExternal: true,
      }),
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
    expect(buttons.map((b) => b.textContent)).toEqual(
      expect.arrayContaining(['DoDD 5000.01', 'DoDI 3115.14']),
    )

    await userEvent.click(within(list).getByRole('button', { name: 'DoDI 3115.14' }))

    // The same selection a click on the canvas makes, so the detail panel and
    // its "Open …" link are reachable by keyboard too.
    expect(await screen.findByTestId('node-detail')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: /open DoDI 3115.14/i }),
    ).toBeInTheDocument()
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
