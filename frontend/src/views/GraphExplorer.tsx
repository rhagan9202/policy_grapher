import { useCallback, useEffect, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { getGraph } from '../api/client'
import type { GraphNode, GraphOut } from '../api/types'

const CORPUS_COLOUR = '#2563eb'
const EXTERNAL_COLOUR = '#94a3b8'

export default function GraphExplorer() {
  const [graph, setGraph] = useState<GraphOut | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)

    getGraph(expanded ? { expand: expanded } : {})
      .then((result) => {
        if (!cancelled) setGraph(result)
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
    if (!node.is_external) setExpanded(node.id)
  }, [])

  if (error) {
    return <div role="alert">Could not load the graph: {error}</div>
  }

  if (!graph) {
    return <p>Loading the graph…</p>
  }

  // react-force-graph mutates the objects it is given; hand it copies.
  const graphData = {
    nodes: graph.nodes.map((node) => ({ ...node })),
    links: graph.edges.map((edge) => ({ ...edge })),
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      <div style={{ flex: 1 }}>
        <ForceGraph2D
          graphData={graphData}
          nodeId="id"
          nodeLabel="label"
          nodeColor={(node: GraphNode) =>
            node.is_external ? EXTERNAL_COLOUR : CORPUS_COLOUR
          }
          nodeRelSize={5}
          linkDirectionalArrowLength={4}
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
            <p>{selected.reference_role ?? 'External reference'}</p>
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
