import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GraphOut } from '../api/types'

const graphProps: Record<string, unknown>[] = []

vi.mock('react-force-graph-2d', () => ({
  default: (props: Record<string, unknown>) => {
    graphProps.push(props)
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

const corpusView: GraphOut = {
  nodes: [
    { id: 'dodd-5000-01', label: 'DoDD 5000.01', reference_role: 'Root Reference', is_external: false },
    { id: 'dodi-3115-14', label: 'DoDI 3115.14', reference_role: 'Sub-Reference', is_external: false },
  ],
  edges: [{ source: 'dodd-5000-01', target: 'dodi-3115-14' }],
  total_nodes: 2,
  returned_nodes: 2,
  truncated: false,
}

const expandedView: GraphOut = {
  nodes: [
    ...corpusView.nodes,
    { id: 'public-law-116-92', label: 'Public Law 116-92', reference_role: null, is_external: true },
  ],
  edges: [
    ...corpusView.edges,
    { source: 'dodi-3115-14', target: 'public-law-116-92' },
  ],
  total_nodes: 3,
  returned_nodes: 3,
  truncated: false,
}

afterEach(() => {
  graphProps.length = 0
  getGraph.mockReset()
})

describe('GraphExplorer', () => {
  it('fetches and renders the default corpus view on mount', async () => {
    getGraph.mockResolvedValue(corpusView)
    render(<GraphExplorer />)

    await waitFor(() => expect(screen.getByTestId('force-graph')).toBeInTheDocument())
    expect(getGraph).toHaveBeenCalledWith({})
    expect(screen.getByText('DoDD 5000.01')).toBeInTheDocument()
  })

  it('shows the name and reference role of a clicked node', async () => {
    getGraph.mockResolvedValue(corpusView)
    render(<GraphExplorer />)
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: 'DoDD 5000.01' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('DoDD 5000.01')
    expect(panel).toHaveTextContent('Root Reference')
  })

  it('refetches with expand when a node is clicked', async () => {
    getGraph.mockResolvedValueOnce(corpusView).mockResolvedValueOnce(expandedView)
    render(<GraphExplorer />)
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: 'DoDI 3115.14' }))

    await waitFor(() =>
      expect(getGraph).toHaveBeenLastCalledWith({ expand: 'dodi-3115-14' }),
    )
    expect(await screen.findByText('Public Law 116-92')).toBeInTheDocument()
  })

  it('renders external nodes in a visually distinct colour from corpus nodes', async () => {
    getGraph.mockResolvedValue(expandedView)
    render(<GraphExplorer />)
    await waitFor(() => screen.getByTestId('force-graph'))

    const props = graphProps[graphProps.length - 1]
    const nodeColor = props.nodeColor as (node: { is_external: boolean }) => string

    const corpusColour = nodeColor({ is_external: false })
    const externalColour = nodeColor({ is_external: true })

    expect(corpusColour).not.toEqual(externalColour)
  })

  it('shows the external reference fallback instead of "null" for a node with no reference role', async () => {
    getGraph.mockResolvedValue(expandedView)
    render(<GraphExplorer />)
    await waitFor(() => screen.getByTestId('force-graph'))

    await userEvent.click(screen.getByRole('button', { name: 'Public Law 116-92' }))

    const panel = await screen.findByTestId('node-detail')
    expect(panel).toHaveTextContent('Public Law 116-92')
    expect(panel).toHaveTextContent('External reference')
    expect(panel.textContent).not.toMatch(/null/i)
  })

  it('reports truncation instead of presenting a partial graph as whole', async () => {
    getGraph.mockResolvedValue({ ...corpusView, total_nodes: 438, returned_nodes: 300, truncated: true })
    render(<GraphExplorer />)

    expect(await screen.findByText(/showing 300 of 438/i)).toBeInTheDocument()
  })

  it('does not claim truncation when the view is complete', async () => {
    getGraph.mockResolvedValue(corpusView)
    render(<GraphExplorer />)
    await waitFor(() => screen.getByTestId('force-graph'))

    expect(screen.queryByText(/showing .* of /i)).not.toBeInTheDocument()
  })

  it('surfaces a fetch failure', async () => {
    getGraph.mockRejectedValue(new Error('backend down'))
    render(<GraphExplorer />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/backend down/i)
  })
})
