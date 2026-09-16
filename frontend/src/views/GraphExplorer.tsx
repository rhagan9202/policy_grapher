import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { Link } from 'react-router-dom'
import { getGraph } from '../api/client'
import type { GraphNode, GraphOut } from '../api/types'
import EmptyState from './EmptyState'

const CORPUS_COLOUR = '#2563eb'
/** Darkened from #94a3b8, which measured 2.56:1 against the white canvas where
 *  WCAG 1.4.11 asks 3:1 of a graphical object you need to see to understand the
 *  content — and corpus-vs-external is the whole point of this drawing. This is
 *  3.52:1. Colour is still not the only channel: external nodes are drawn
 *  smaller, and the list beside the canvas says "external" in words. */
const EXTERNAL_COLOUR = '#7b8a9e'

/** Relative node area. The second, non-colour channel for 1.4.1: a reader who
 *  cannot separate the blue from the grey can still separate the sizes. */
const CORPUS_NODE_VALUE = 1
const EXTERNAL_NODE_VALUE = 0.4

const LABEL_COLOUR = '#0f172a'
const LABEL_HALO_COLOUR = '#ffffff'
const EXTERNAL_LABEL_COLOUR = '#475569'

const NODE_RELATIVE_SIZE = 5
const LABEL_FONT_SIZE = 13
/** Halo width in screen pixels; divided by zoom so it stays constant. */
const LABEL_HALO_WIDTH = 3

/** d3-force defaults are -30 and 30, which leave 72 edges over 23 nodes
 *  bunched into an unreadable knot. */
const CHARGE_STRENGTH = -200
const LINK_DISTANCE = 60
/** Below this zoom, external labels are suppressed — the include_external
 *  view holds up to 300 of them and their names run past 100 characters. */
const EXTERNAL_LABEL_ZOOM = 1.5
const RECIPROCAL_CURVATURE = 0.25

type LinkEndpoint = string | { id: string }

/** The force simulation replaces endpoint ids with the node objects themselves
 *  once it starts, so links arrive in both shapes over a view's lifetime. */
function endpointId(endpoint: LinkEndpoint): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id
}

function edgeKey(source: string, target: string): string {
  return `${source} ${target}`
}

/** The slice of react-force-graph's imperative handle this view drives. */
type ForceGraphHandle = {
  d3Force: (name: string) => unknown
  d3ReheatSimulation: () => void
  pauseAnimation: () => void
  resumeAnimation: () => void
}

export default function GraphExplorer() {
  const forceGraphRef = useRef<ForceGraphHandle | undefined>(undefined)
  const [graph, setGraph] = useState<GraphOut | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  // Off by default, which is the corpus-first view ADR-002 describes — 23
  // documents rather than 436, and readable. What was missing is the way back:
  // `GET /graph` has taken `include_external` since DI-1 and `GraphOptions` has
  // modelled it since the client was written, and no control ever passed it. The
  // opening screen drew 5% of the corpus and had no way to say so, because the
  // API's `truncated` is about the fetch and not about the omission.
  const [includeExternal, setIncludeExternal] = useState(false)

  // ForceGraph2D given no width/height sizes its canvas to window.innerWidth
  // and innerHeight rather than to its container, which pushed the 320px panel
  // beside it clean off the viewport at every width measured — 1280 through
  // 2560 (STORY-039). Measuring the container is the fix; a ResizeObserver
  // keeps it right when the window changes.
  //
  // A *callback* ref, not a mount effect. This view returns "Loading the
  // graph…" until the first fetch resolves, so the measured element does not
  // exist on the render that a `useEffect(…, [])` runs after. That effect saw
  // `canvasRef.current === null`, returned without observing, and — having no
  // dependencies — never ran again once the real container mounted. The size
  // stayed at its 0×0 initial value for the life of the view, so every graph
  // with data rendered a 0×0 canvas: a blank page beside a working panel, with
  // no error anywhere. A callback ref runs when the node itself mounts, which
  // is the event that actually matters here.
  const observerRef = useRef<ResizeObserver | null>(null)
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 })

  const canvasRef = useCallback((element: HTMLDivElement | null) => {
    observerRef.current?.disconnect()
    observerRef.current = null
    if (!element) return

    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setCanvasSize({ width: Math.round(width), height: Math.round(height) })
    })
    observer.observe(element)
    observerRef.current = observer
  }, [])

  useEffect(() => {
    let cancelled = false

    getGraph({
      ...(expanded ? { expand: expanded } : {}),
      ...(includeExternal ? { includeExternal: true } : {}),
    })
      .then((result) => {
        if (!cancelled) {
          setGraph(result)
          // Cleared here rather than in the effect body: a synchronous setState in an
          // effect costs an extra render pass (react-hooks/set-state-in-effect), and
          // clearing on arrival also stops a stale error blanking mid-refetch.
          setError(null)
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : 'Failed to load the graph.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [expanded, includeExternal])

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelected(node)
    // Only corpus nodes expand: an external document has no external
    // neighbours of its own, so expanding one would be a guaranteed no-op.
    if (!node.is_external) setExpanded(node.id)
  }, [])

  // WCAG 2.2.2. The force simulation settles in 8.8 to 10.4 seconds depending on
  // node count, which is well past the five-second threshold for motion that
  // needs a stop. `prefers-reduced-motion` cannot reach it — the rule in
  // styles.css governs CSS animation, and this is a canvas simulation.
  // How many of the drawn nodes are external, which is not the same question as
  // whether the toggle is on: an expansion pulls them in regardless.
  const externalsShown = useMemo(
    () => (graph?.nodes ?? []).filter((node) => node.is_external).length,
    [graph],
  )

  const [frozen, setFrozen] = useState(false)
  const toggleLayout = useCallback(() => {
    const handle = forceGraphRef.current
    if (!handle) return
    if (frozen) {
      handle.resumeAnimation()
    } else {
      handle.pauseAnimation()
    }
    setFrozen(!frozen)
  }, [frozen])

  // react-force-graph mutates the objects it is given (position, velocity,
  // simulation state) and treats a new `graphData` reference as new data.
  // Memoise on `graph` so clicks that don't change the dataset (e.g.
  // selecting an external node) don't hand the library fresh unpositioned
  // copies and reset the force layout.
  const graphData = useMemo(
    () => ({
      nodes: graph ? graph.nodes.map((node) => ({ ...node })) : [],
      links: graph ? graph.edges.map((edge) => ({ ...edge })) : [],
    }),
    [graph],
  )

  // Edges whose reverse also exists. Drawn straight they land exactly on top
  // of one another, so each pair is bowed apart instead.
  const reciprocalEdges = useMemo(() => {
    const edges = graph?.edges ?? []
    const present = new Set(edges.map((edge) => edgeKey(edge.source, edge.target)))
    return new Set(
      edges
        .filter((edge) => present.has(edgeKey(edge.target, edge.source)))
        .map((edge) => edgeKey(edge.source, edge.target)),
    )
  }, [graph])

  const linkCurvature = useCallback(
    (link: { source: LinkEndpoint; target: LinkEndpoint }) =>
      reciprocalEdges.has(edgeKey(endpointId(link.source), endpointId(link.target)))
        ? RECIPROCAL_CURVATURE
        : 0,
    [reciprocalEdges],
  )

  const paintNodeLabel = useCallback(
    (node: GraphNode & { x?: number; y?: number }, ctx: CanvasRenderingContext2D, globalScale: number) => {
      if (node.is_external && globalScale < EXTERNAL_LABEL_ZOOM) return

      const fontSize = LABEL_FONT_SIZE / globalScale
      const x = node.x ?? 0
      const y = (node.y ?? 0) + NODE_RELATIVE_SIZE + fontSize * 0.4

      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'

      // Halo first: labels sit over edges and other nodes, and dark text alone
      // is unreadable against them.
      ctx.strokeStyle = LABEL_HALO_COLOUR
      ctx.lineWidth = LABEL_HALO_WIDTH / globalScale
      ctx.lineJoin = 'round'
      ctx.strokeText(node.label, x, y)

      ctx.fillStyle = node.is_external ? EXTERNAL_LABEL_COLOUR : LABEL_COLOUR
      ctx.fillText(node.label, x, y)
    },
    [],
  )

  // 'after' leaves the circle and the pointer hit area with the library; we
  // only add text on top.
  const paintMode = useCallback(() => 'after' as const, [])

  // Loosen the layout beyond d3's defaults, which pack this graph too tightly
  // to read. Reapplied per dataset, since expanding swaps the node set.
  useEffect(() => {
    const forceGraph = forceGraphRef.current
    if (!forceGraph) return

    const charge = forceGraph.d3Force('charge') as
      | { strength: (value: number) => unknown }
      | undefined
    const link = forceGraph.d3Force('link') as
      | { distance: (value: number) => unknown }
      | undefined

    charge?.strength(CHARGE_STRENGTH)
    link?.distance(LINK_DISTANCE)
    forceGraph.d3ReheatSimulation()
  }, [graph])

  if (error) {
    return <div role="alert">Could not load the graph: {error}</div>
  }

  if (!graph) {
    return <p>Loading the graph…</p>
  }

  return (
    // Laid out in styles.css rather than here, so a media query can restack
    // the panel under the canvas: at 768px a fixed 20rem panel took 42% of the
    // window and the graph was clipped off both edges.
    <div className="graph">
      {/* `role="img"` with a name that says what is drawn. The canvas itself is
          a bare <canvas> the library emits — no role, no text, nothing in the
          accessibility tree — so for a screen-reader user this sentence *is* the
          picture, and the list in the panel is how they operate it. Marking the
          subtree as one image also stops assistive tech wandering into a canvas
          that has nothing to say. */}
      <div
        ref={canvasRef}
        className="graph-canvas"
        role="img"
        aria-label={
          `Reference graph: ${graph.returned_nodes} document` +
          `${graph.returned_nodes === 1 ? '' : 's'} and ${graph.edges.length} ` +
          `reference${graph.edges.length === 1 ? '' : 's'} between them. ` +
          `The same documents are listed beside the drawing as buttons.`
        }
      >
        <ForceGraph2D
          // The library's ref type is generic over the inferred node and link
          // shapes; ForceGraphHandle names only the two methods used here.
          ref={forceGraphRef as never}
          width={canvasSize.width}
          height={canvasSize.height}
          graphData={graphData}
          nodeId="id"
          nodeLabel="label"
          nodeColor={(node: GraphNode) =>
            node.is_external ? EXTERNAL_COLOUR : CORPUS_COLOUR
          }
          nodeRelSize={NODE_RELATIVE_SIZE}
          nodeVal={(node: GraphNode) =>
            node.is_external ? EXTERNAL_NODE_VALUE : CORPUS_NODE_VALUE
          }
          nodeCanvasObjectMode={paintMode}
          nodeCanvasObject={paintNodeLabel}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkCurvature={linkCurvature}
          onNodeClick={handleNodeClick}
        />
      </div>

      <aside className="graph-panel">
        <h1>Policy Grapher</h1>

        {graph.total_nodes === 0 && <EmptyState />}

        {graph.total_nodes > 0 && (
          <>
            <p className="graph-count">
              {/* `total_nodes` counts what matched the query, not what the corpus
                  holds — with external references off it answers 23 of 23 over a
                  graph of 436. So a bare "N of M" is no help here, and the
                  truncation notice this replaces was worse: it fired on
                  `truncated`, which the API sets only when it dropped rows from
                  what it was *asked* for, so the default view reported nothing
                  missing at all while hiding 95% of the corpus.
                  What the reader needs is the exclusion named. */}
              {/* Two independent facts, so two sentences. The cap can bite with
                  external references either way — a corpus of its own past the
                  render cap truncates too — and the exclusion applies only while
                  the toggle is off. */}
              {graph.truncated ? (
                <>
                  Showing {graph.returned_nodes} of {graph.total_nodes} documents —
                  capped, narrow the view to see the rest.
                </>
              ) : (
                <>
                  Showing {graph.returned_nodes} document
                  {graph.returned_nodes === 1 ? '' : 's'}
                  {/* "in the corpus" is a claim about all of them, so it can
                      only be made when all of them are. */}
                  {externalsShown ? '' : ' in the corpus'}.
                </>
              )}
              {/* Gated on what is actually drawn, not on the toggle alone.
                  Expanding a corpus node pulls that document's external
                  references onto the canvas, so this used to read "Showing 40
                  documents in the corpus. Documents cited but never ingested are
                  hidden." over a picture in which 17 of the 40 were precisely
                  those documents — the caption contradicting the drawing at the
                  most natural gesture on the screen. */}
              {externalsShown ? (
                <>
                  {' '}
                  {externalsShown} of them {externalsShown === 1 ? 'is' : 'are'}{' '}
                  cited but not ingested.
                </>
              ) : (
                !includeExternal && (
                  <> Documents cited but never ingested are hidden.</>
                )
              )}
            </p>

            <label className="graph-toggle">
              <input
                type="checkbox"
                checked={includeExternal}
                onChange={(event) => setIncludeExternal(event.target.checked)}
              />{' '}
              Include external references
            </label>

            <ul className="legend" aria-label="Legend">
              <li>
                <span className="swatch swatch-corpus" aria-hidden="true" />
                In the corpus — ingested, with a page of its own
              </li>
              <li>
                <span className="swatch swatch-external" aria-hidden="true" />
                Cited but not ingested — the graph holds its name, not its text
              </li>
            </ul>
            <p className="legend-note">
              {/* The alternative was lowering EXTERNAL_LABEL_ZOOM, which exists
                  because the external view holds up to 300 names running past
                  100 characters. Saying why a label is missing costs nothing and
                  keeps the zoomed-out view readable. */}
              External names are hidden until you zoom in to read them.
            </p>

            <button type="button" onClick={toggleLayout}>
              {frozen ? 'Resume layout' : 'Freeze layout'}
            </button>

            {/* The canvas is a mouse-only control: nothing in it is focusable,
                so selecting a document, expanding it, and reaching its page were
                all unavailable without a pointer — while the panel said "Click a
                document to see its details", an instruction a keyboard user
                cannot follow. These are the same nodes driving the same handler,
                so the two routes cannot drift apart.

                Visible rather than screen-reader-only: a list of what is on the
                canvas is useful to everyone at 300 nodes, where the drawing is a
                hairball and the labels collide. */}
            <div
              className="graph-nodes"
              role="group"
              aria-label="Documents in the graph"
            >
              <ul>
                {graph.nodes.map((node) => (
                  <li key={node.id}>
                    <button type="button" onClick={() => handleNodeClick(node)}>
                      {node.label}
                    </button>
                    {/* The third channel, after colour and size: a word. */}
                    {node.is_external && <span className="node-kind"> external</span>}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        {selected ? (
          <div data-testid="node-detail">
            <h2>{selected.label}</h2>
            <p>{selected.is_external ? 'External reference' : 'Corpus document'}</p>
            {/* The graph shows what a document is connected to and nothing about
                what it says. Its text, editions and obligations are one page
                away, and until now that page was reachable only by going to
                Documents and finding the same document again by name. */}
            <p>
              <Link to={`/documents/${selected.id}`}>Open {selected.label}</Link>
            </p>
          </div>
        ) : (
          <p>Click a document to see its details and pull in its external references.</p>
        )}

        {expanded && (
          <button type="button" onClick={() => setExpanded(null)}>
            Collapse to corpus
          </button>
        )}
      </aside>
    </div>
  )
}
