import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { getGraph } from '../api/client'
import type { GraphNode, GraphOut } from '../api/types'

const CORPUS_COLOUR = '#2563eb'
const EXTERNAL_COLOUR = '#94a3b8'

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
}

export default function GraphExplorer() {
  const forceGraphRef = useRef<ForceGraphHandle | undefined>(undefined)
  const [graph, setGraph] = useState<GraphOut | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    getGraph(expanded ? { expand: expanded } : {})
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
  }, [expanded])

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelected(node)
    // Only corpus nodes expand: an external document has no external
    // neighbours of its own, so expanding one would be a guaranteed no-op.
    if (!node.is_external) setExpanded(node.id)
  }, [])

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
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ flex: 1 }}>
        <ForceGraph2D
          // The library's ref type is generic over the inferred node and link
          // shapes; ForceGraphHandle names only the two methods used here.
          ref={forceGraphRef as never}
          graphData={graphData}
          nodeId="id"
          nodeLabel="label"
          nodeColor={(node: GraphNode) =>
            node.is_external ? EXTERNAL_COLOUR : CORPUS_COLOUR
          }
          nodeRelSize={NODE_RELATIVE_SIZE}
          nodeCanvasObjectMode={paintMode}
          nodeCanvasObject={paintNodeLabel}
          linkDirectionalArrowLength={4}
          linkDirectionalArrowRelPos={1}
          linkCurvature={linkCurvature}
          onNodeClick={handleNodeClick}
        />
      </div>

      <aside style={{ width: 320, padding: '1rem', borderLeft: '1px solid #e2e8f0' }}>
        <h1>Policy Grapher</h1>

        {graph.truncated && (
          <p>
            Showing {graph.returned_nodes} of {graph.total_nodes} nodes.
          </p>
        )}

        {selected ? (
          <div data-testid="node-detail">
            <h2>{selected.label}</h2>
            <p>{selected.is_external ? 'External reference' : 'Corpus document'}</p>
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
