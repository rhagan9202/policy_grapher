import { render, screen, waitFor } from '@testing-library/react'
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
    expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument()
  })

  it('shows the name and kind of a clicked node', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: 'DoDD 5000.01' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('DoDD 5000.01')
    expect(panel).toHaveTextContent('Corpus document')
  })

  it('refetches with expand when a node is clicked', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValueOnce(expandedView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: 'DoDI 3115.14' }))

    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({ expand: 'dodi-3115-14' }),
    )
    expect(await screen.findByText('Public Law 116-92')).toBeInTheDocument()
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

    await userEvent.click(screen.getByRole('button', { name: 'Public Law 116-92' }))

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

  it('does not claim truncation when the view is complete', async () => {
    getGraph.mockResolvedValue(corpusView)
    showGraphExplorer()
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(screen.queryByText(/showing .* of /i)).not.toBeInTheDocument()
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
