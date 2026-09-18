import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type NodeObject } from 'react-force-graph-2d'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, getGraph } from '../api/client'
import type { GraphNode, GraphOut } from '../api/types'

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

/** d3-force defaults are -30 and 30, which leave a neighbourhood's edges
 *  bunched into an unreadable knot. */
const CHARGE_STRENGTH = -200
const LINK_DISTANCE = 60
/** Below this zoom, external labels are suppressed — their names run past 100
 *  characters and a dense neighbourhood collides at every one of them. */
const EXTERNAL_LABEL_ZOOM = 1.5
const RECIPROCAL_CURVATURE = 0.25

/** Camera transition, and the padding left around the fitted neighbourhood. */
const CAMERA_MS = 400
const CAMERA_PADDING = 60
/** Zoom bounds for the computed fit: a one-node neighbourhood would otherwise
 *  scale to absurdity, and a very wide one past the point of being readable. */
const MIN_ZOOM = 0.15
const MAX_ZOOM = 2.5

/** The API bounds depth at three; asking for more is a 422, and a reader who
 *  wanted the whole corpus asked the wrong question. */
const MIN_DEPTH = 1
const MAX_DEPTH = 3

type LinkEndpoint = string | { id: string }

/** The force simulation replaces endpoint ids with the node objects themselves
 *  once it starts, so links arrive in both shapes over a view's lifetime. */
function endpointId(endpoint: LinkEndpoint): string {
  return typeof endpoint === 'string' ? endpoint : endpoint.id
}

function edgeKey(source: string, target: string): string {
  return `${source} ${target}`
}

/** A node as the renderer holds it: our fields plus the simulation's own
 *  position and velocity, which it writes onto the object in place. The library
 *  already names that shape, so this is an alias rather than a second copy. */
type DrawnNode = NodeObject<GraphNode>

type HeldResult = {
  slug: string
  depth: number
  result: GraphOut
  data: { nodes: DrawnNode[]; links: GraphOut['edges'] }
}

const NOTHING_DRAWN = { nodes: [] as DrawnNode[], links: [] as GraphOut['edges'] }

export default function GraphExplorer() {
  // Focus lives in the URL, so the view is addressable, shareable, and
  // reversible by browser history (KTD5). It also supplies the back behaviour
  // the map otherwise lacks: the control that used to provide it collapsed to
  // the corpus, which is the corpus-wide affordance R12 removes.
  const [searchParams, setSearchParams] = useSearchParams()
  const focus = searchParams.get('focus')
  const depthParam = Number(searchParams.get('depth'))
  // Integer, not merely finite. The API types depth as an int and refuses
  // `?depth=1.5` with a 422 — and since this parameter rides in the URL so a
  // view can be shared and bookmarked, a hand-edited or truncated link is an
  // ordinary way to arrive here, not a malformed-input edge case.
  const depth =
    Number.isInteger(depthParam) && depthParam >= MIN_DEPTH
      ? Math.min(depthParam, MAX_DEPTH)
      : MIN_DEPTH

  const forceGraphRef = useRef<ForceGraphMethods<GraphNode> | undefined>(undefined)
  // Held with the request that produced it. Without the slug, every label on
  // screen is computed from the current URL while the data underneath is the
  // previous document's — so a focus change drew one neighbourhood under
  // another's name, and a 404 on one document was reported against the next.
  const [held, setHeld] = useState<HeldResult | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [failure, setFailure] = useState<
    { slug: string; message: string; missing: boolean } | null
  >(null)
  /** Bumped by the retry control, which is the only thing that re-runs a fetch
   *  the URL has not changed. */
  const [reloadKey, setReloadKey] = useState(0)

  // ForceGraph2D given no width/height sizes its canvas to window.innerWidth
  // and innerHeight rather than to its container, which pushed the 320px panel
  // beside it clean off the viewport at every width measured — 1280 through
  // 2560 (STORY-039). Measuring the container is the fix; a ResizeObserver
  // keeps it right when the window changes.
  //
  // A *callback* ref, not a mount effect. This view renders no canvas at all
  // until a focused document has loaded, so the measured element does not exist
  // on the render a `useEffect(…, [])` would run after. That effect saw a null
  // ref, returned without observing, and — having no dependencies — never ran
  // again once the real container mounted.
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

  // Node objects, held across fetches by id. react-force-graph reheats its
  // simulation to full strength on every data change, and a node's position
  // survives only through JavaScript object identity — not through a matching
  // id. Handing the library fresh objects on each fetch, which is what this
  // view used to do, re-scattered the whole layout every time a reader expanded
  // the neighbourhood they were reading (KTD3).
  const nodesById = useRef(new Map<string, DrawnNode>())
  /** Which focus the camera has already been placed for; centring again on
   *  every settle would fight a reader who has panned away. */
  const centredFor = useRef<string | null>(null)
  /** How many nodes the camera was last fitted around; an expansion changes it
   *  and the new arrivals would otherwise sit outside the frame. */
  const fittedFor = useRef<number | null>(null)
  /** Which focus the held positions belong to. A new focus is a different
   *  neighbourhood, so its positions are not worth keeping; a deeper walk of
   *  the same one is the case this map exists to serve. */
  const mapFocus = useRef<string | null>(null)

  // Merging runs when a result arrives, never during render: this reads and
  // writes refs, and a render may be replayed or discarded.
  const merge = useCallback(
    (result: GraphOut, forSlug: string) => {
      if (mapFocus.current !== forSlug) {
        // All three are invalidated together. Leaving `fittedFor` set is
        // correct only while the camera guard is an OR; tighten that guard to
        // require both conditions and a new neighbourhood that happens to hold
        // the same number of nodes would silently skip its fit.
        nodesById.current.clear()
        centredFor.current = null
        fittedFor.current = null
        mapFocus.current = forSlug
      }

      const arriving = new Set(result.nodes.map((node) => node.id))
      // Built once rather than re-scanning every edge for every arriving node,
      // which is the same answer at O(nodes + edges) instead of O(new x edges).
      const neighboursById = new Map<string, string[]>()
      const link = (from: string, to: string) => {
        const existing = neighboursById.get(from)
        if (existing) existing.push(to)
        else neighboursById.set(from, [to])
      }
      for (const edge of result.edges) {
        link(edge.source, edge.target)
        link(edge.target, edge.source)
      }
      const nodes = result.nodes.map((node) => {
        const drawn = nodesById.current.get(node.id)
        if (drawn) {
          // Assign onto the held object rather than replacing it: the simulation
          // owns x/y/vx/vy on this object and the renderer identifies it by
          // reference, not by id.
          Object.assign(drawn, node)
          return drawn
        }
        const fresh: DrawnNode = { ...node }
        // Seed a newly revealed node where the drawn node that revealed it sits.
        // Dropped at the origin it flies across the canvas as the simulation
        // pulls it home, which is the re-scatter this map exists to prevent,
        // arriving one node at a time.
        const revealer = (neighboursById.get(node.id) ?? [])
          .map((id) => nodesById.current.get(id))
          .find((candidate) => candidate?.x !== undefined)
        if (revealer) {
          fresh.x = revealer.x
          fresh.y = revealer.y
        }
        nodesById.current.set(node.id, fresh)
        return fresh
      })

      for (const id of nodesById.current.keys()) {
        if (!arriving.has(id)) nodesById.current.delete(id)
      }

      return { nodes, links: result.edges.map((edge) => ({ ...edge })) }
    },
    [],
  )

  useEffect(() => {
    if (!focus) return
    let cancelled = false

    getGraph({ focus, depth })
      .then((result) => {
        if (!cancelled) {
          setHeld({ slug: focus, depth, result, data: merge(result, focus) })
          // Cleared on arrival rather than in the effect body: a synchronous
          // setState in an effect costs an extra render pass, and clearing here
          // also stops a stale error blanking the view mid-refetch.
          setFailure(null)
        }
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        const missing = cause instanceof ApiError && cause.status === 404
        setFailure({
          slug: focus,
          missing,
          message:
            cause instanceof Error ? cause.message : 'Failed to load the neighbourhood.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [focus, depth, reloadKey, merge])


  // Matched on the slug alone, deliberately, not on slug and depth together.
  // A different document is a different neighbourhood, so drawing the old one
  // under the new name is the defect. A deeper walk of the *same* document is
  // not: the caption names that document either way and the count describes
  // what is actually on the canvas, so holding the drawing while the larger set
  // loads keeps it honest and keeps the layout the reader was using — which is
  // the whole point of holding node identity across fetches.
  const matched = held && held.slug === focus ? held : null
  const graph = matched?.result ?? null
  const graphData = matched?.data ?? NOTHING_DRAWN
  /** A deeper walk of the document already drawn is in flight. */
  const refreshing = Boolean(matched && matched.depth !== depth)
  // An error belongs to the slug that produced it. Navigating away from a
  // failure falls through to loading rather than inheriting someone else's.
  const error = failure && failure.slug === focus ? failure : null

  const focusNode = focus ? graphData.nodes.find((node) => node.id === focus) : undefined
  // Derived, not cleared in an effect: a selection from the previous
  // neighbourhood is simply not present in this one, and browser back changes
  // focus without passing through any handler that could reset it.
  const activeSelection = selected
    ? (graphData.nodes.find((node) => node.id === selected.id) ?? null)
    : null

  const handleNodeClick = useCallback((node: GraphNode) => {
    // Selecting inspects; moving focus is the separate control in the detail
    // below (KTD6). The old handler did both at once, so there was no way to
    // read a neighbour without also leaving the document you were reading.
    setSelected(node)
  }, [])

  const moveFocus = useCallback(
    (slug: string) => {
      setSearchParams({ focus: slug, depth: String(MIN_DEPTH) })
    },
    [setSearchParams],
  )

  const expand = useCallback(() => {
    if (!focus || depth >= MAX_DEPTH) return
    // A history entry, so browser back is the way out of an expansion as well
    // as out of a focus change.
    setSearchParams({ focus, depth: String(depth + 1) })
  }, [focus, depth, setSearchParams])

  // Placed once the layout settles rather than on mount: on mount the nodes have
  // no positions yet, so both calls would aim at the origin.
  //
  // The two halves answer different questions and so are guarded differently.
  // Centring says "here is the document you asked for", which is only news when
  // the focus changed — doing it after every settle would drag the camera back
  // each time a reader panned somewhere and the simulation twitched. Fitting
  // says "here is all of it", which is news whenever the drawn set changed: an
  // expansion adds nodes outside the old frame, and without a re-fit they are
  // simply off the edge of the canvas. Neither call moves a node, so the
  // positions an expansion preserves stay preserved.
  const frameCamera = useCallback(() => {
    if (!focus) return
    const handle = forceGraphRef.current
    if (!handle) return

    // The same object `graphData.nodes` holds — `merge` puts the held values
    // there — so this is the one lookup path for "the focused node".
    const node = focusNode
    if (node?.x === undefined || node.y === undefined) return

    // Nothing to frame against until the canvas has been measured. Without
    // this the half-width is negative, the scale clamps to the floor, and the
    // guards below latch that framing permanently — the settle that would have
    // corrected it has already happened.
    if (!canvasSize.width || !canvasSize.height) return

    const drawn = graphData.nodes.length
    const changed = fittedFor.current !== drawn
    const arrived = centredFor.current !== focus
    if (!changed && !arrived) return

    // `zoomToFit` frames the bounding box, which is a different centre from the
    // focused node whenever the neighbourhood is lopsided — and it is, since one
    // heavily-cited neighbour drags the box away. Calling both leaves the later
    // one to win: fit-then-centre pushes the far side off the canvas, and
    // centre-then-fit makes the centring decorative. So the zoom is computed
    // around the focused node instead, which is the only way to hold it in the
    // middle *and* keep the furthest neighbour on screen.
    // Captured after the guard above: the narrowing does not follow `node` into
    // the closures below, and `tsc -b` is stricter about that than the app
    // config alone.
    const centreX = node.x
    const centreY = node.y

    const halfWidth = canvasSize.width / 2 - CAMERA_PADDING
    const halfHeight = canvasSize.height / 2 - CAMERA_PADDING
    let spreadX = 1
    let spreadY = 1
    for (const other of graphData.nodes) {
      spreadX = Math.max(spreadX, Math.abs((other.x ?? centreX) - centreX))
      spreadY = Math.max(spreadY, Math.abs((other.y ?? centreY) - centreY))
    }
    const scale = Math.min(halfWidth / spreadX, halfHeight / spreadY)

    handle.centerAt(centreX, centreY, CAMERA_MS)
    // Bounded: a single-node neighbourhood would otherwise compute an enormous
    // scale, and a very wide one a scale too small to read.
    handle.zoom(Math.min(Math.max(scale, MIN_ZOOM), MAX_ZOOM), CAMERA_MS)
    fittedFor.current = drawn
    centredFor.current = focus
  }, [focus, focusNode, graphData.nodes, canvasSize.width, canvasSize.height])

  // A settle is not the only thing that invalidates a framing. Once the engine
  // stops it never calls back again, so a window resize — or crossing the
  // breakpoint where the panel restacks and the canvas changes height — would
  // otherwise leave the neighbourhood framed for a box that no longer exists,
  // with no path back. `fittedFor` is cleared so the refit is not mistaken for
  // a settle that changed nothing.
  // Held in a ref rather than depended on directly: `frameCamera` is rebuilt
  // whenever the drawing changes, so depending on it would run this effect on
  // every fetch — clearing the guard and re-framing against positions the
  // engine has not laid out yet. A resize is the only thing that belongs here.
  const frameCameraRef = useRef(frameCamera)
  // Synced in an effect rather than assigned during render, which React forbids.
  // Declared above the resize effect on purpose: effects in one commit run in
  // declaration order, so on the render where the canvas is remeasured this has
  // already stored the current closure by the time the resize effect calls it.
  useEffect(() => {
    frameCameraRef.current = frameCamera
  }, [frameCamera])

  useEffect(() => {
    if (!canvasSize.width || !canvasSize.height) return
    fittedFor.current = null
    frameCameraRef.current()
  }, [canvasSize.width, canvasSize.height])

  const externalsShown = useMemo(
    () => (graph?.nodes ?? []).filter((node) => node.is_external).length,
    [graph],
  )

  const documentsDrawn = graph
    ? `${graph.returned_nodes} document${graph.returned_nodes === 1 ? '' : 's'}`
    : ''

  // WCAG 2.2.2. The force simulation settles well past the five-second
  // threshold for motion that needs a stop, and `prefers-reduced-motion` cannot
  // reach it — the rule in styles.css governs CSS animation, and this is a
  // canvas simulation.
  const [frozen, setFrozen] = useState(false)
  const toggleLayout = useCallback(() => {
    // The flag flips whether or not a handle is present: it records what the
    // reader asked for, and the effect above applies it to whichever instance
    // is current. Returning early here left the button and the flag disagreeing
    // about a canvas that was not mounted.
    const handle = forceGraphRef.current
    if (frozen) {
      handle?.resumeAnimation()
    } else {
      handle?.pauseAnimation()
    }
    setFrozen(!frozen)
  }, [frozen])

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
    (node: DrawnNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
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

  /** Whether a canvas is on screen — the exact condition its JSX is guarded by.
   *
   *  What invalidates the instance configuration below is the canvas being
   *  rebuilt, and the response object changing is only a proxy for that. Since
   *  the canvas now unmounts on a failure, a retry answering with an equal
   *  response mounts a fresh, unconfigured instance under an unchanged `graph`
   *  — d3 defaults, no reheat, and the reader's frozen choice dropped. */
  const canvasMounted = Boolean(focus && !error && graph)

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

    // Reassert the reader's choice against this instance. `frozen` is component
    // state, but what it describes is one canvas's animation loop — and that
    // canvas now unmounts on a failure and remounts on retry, animating by
    // default. Without this a retry restarts the motion someone deliberately
    // stopped, under a button still offering to resume it; and a reheat while
    // frozen never ticks, so the new neighbourhood is never laid out, never
    // painted, and never settles, which is the only thing that places the
    // camera.
    if (frozen) {
      forceGraph.pauseAnimation()
    } else {
      forceGraph.resumeAnimation()
    }
  }, [graph, canvasMounted, frozen])

  const drawing = Boolean(focus && graph && !error)

  return (
    // Laid out in styles.css rather than here, so a media query can restack
    // the panel under the canvas: at 768px a fixed 20rem panel took 42% of the
    // window and the graph was clipped off both edges.
    //
    // `graph-solo` is the no-canvas case — no document focused, or the request
    // failed. Both are landing surfaces rather than edge cases, and the panel is
    // a 20rem sidebar only when there is a drawing for it to sit beside.
    <div className={drawing ? 'graph' : 'graph graph-solo'}>
      {focus && graph && !error && (
        <div
          ref={canvasRef}
          className="graph-canvas"
          role="img"
          aria-busy={refreshing}
          aria-label={
            `Dependency map centred on ${focusNode?.label ?? focus}: ${documentsDrawn} ` +
            `and ${graph.edges.length} reference${graph.edges.length === 1 ? '' : 's'} ` +
            'between them.' +
            (graph.truncated
              ? ` Showing ${graph.returned_nodes} of ${graph.total_nodes}; the rest were dropped by ${graph.truncation_basis ?? 'the render cap'}.`
              : '') +
            ' The same documents are listed beside the drawing as buttons.'
          }
        >
          <ForceGraph2D
            ref={forceGraphRef}
            width={canvasSize.width}
            height={canvasSize.height}
            graphData={graphData}
            nodeId="id"
            nodeLabel="label"
            nodeColor={(node: DrawnNode) =>
              node.is_external ? EXTERNAL_COLOUR : CORPUS_COLOUR
            }
            nodeRelSize={NODE_RELATIVE_SIZE}
            nodeVal={(node: DrawnNode) =>
              node.is_external ? EXTERNAL_NODE_VALUE : CORPUS_NODE_VALUE
            }
            nodeCanvasObjectMode={paintMode}
            nodeCanvasObject={paintNodeLabel}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            linkCurvature={linkCurvature}
            onNodeClick={handleNodeClick}
            onEngineStop={frameCamera}
          />
        </div>
      )}

      <aside className="graph-panel">
        <h1>Policy Grapher</h1>

        {/* The landing state on every cold start and every navigation click,
            not an edge case. It deliberately does not fall back to the
            corpus-wide view: that is the view R12 removes, and it is the
            fallback an implementer reaches for by default.

            It also does not reuse the shared empty-state component, whose text
            asserts the corpus is empty. Knowing that would take the corpus-wide
            read this view no longer makes, and the sentence is false whenever
            documents exist. */}
        {!focus && (
          <div role="status">
            <p>
              <strong>No document is focused.</strong>
            </p>
            <p>
              The map draws one document and what it depends on. Choose one from{' '}
              <Link to="/documents">Documents</Link>, or <Link to="/ingest">Ingest</Link> a
              new one and land on it.
            </p>
          </div>
        )}

        {focus && error && (
          <div role="alert">
            {error.missing ? (
              <>
                <p>
                  <strong>That document was not found.</strong> Nothing in the graph
                  answers to <code>{focus}</code> — it may have been removed, or the
                  address may be mistyped.
                </p>
                <p>
                  <Link to="/documents">Browse Documents</Link> to pick one that exists.
                </p>
              </>
            ) : (
              <>
                <p>
                  <strong>Could not load the neighbourhood.</strong> {error.message}
                </p>
                <p>
                  <Link to="/documents">Browse Documents</Link>, or try again.
                </p>
              </>
            )}
            <button type="button" onClick={() => setReloadKey((key) => key + 1)}>
              Retry
            </button>
          </div>
        )}

        {focus && !error && !graph && <p>Loading the neighbourhood…</p>}

        {focus && !error && graph && (
          <>
            <p className="graph-count">
              {graph.truncated ? (
                <>
                  Showing {graph.returned_nodes} of {graph.total_nodes} documents around{' '}
                  {focusNode?.label ?? focus} — capped, expand less to see fewer.
                </>
              ) : (
                <>
                  Showing {documentsDrawn} around {focusNode?.label ?? focus}.
                </>
              )}
              {externalsShown ? (
                <>
                  {' '}
                  {externalsShown} of them {externalsShown === 1 ? 'is' : 'are'} cited but
                  not ingested.
                </>
              ) : null}
            </p>

            <button type="button" onClick={expand} disabled={depth >= MAX_DEPTH}>
              {depth >= MAX_DEPTH ? 'Expanded as far as it goes' : 'Expand one degree'}
            </button>

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
              External names are hidden until you zoom in to read them.
            </p>

            <button type="button" onClick={toggleLayout}>
              {frozen ? 'Resume layout' : 'Freeze layout'}
            </button>

            {/* The canvas is a mouse-only control: nothing in it is focusable,
                so selecting a document and reaching its page were both
                unavailable without a pointer. These are the same nodes driving
                the same handler, so the two routes cannot drift apart.

                The focused document is named here in words. Centring the camera
                on it is a signal only sighted readers receive, and since
                selecting and focusing now have different consequences, a reader
                who cannot see the camera still has to be able to tell which
                document the neighbourhood is drawn around. */}
            <div
              className="graph-nodes"
              role="group"
              aria-label="Documents in the graph"
            >
              <ul>
                {graphData.nodes.map((node) => (
                  <li key={node.id}>
                    <button type="button" onClick={() => handleNodeClick(node)}>
                      {node.label}
                      {node.id === focus && <span className="node-kind"> focused</span>}
                    </button>
                    {node.is_external && <span className="node-kind"> external</span>}
                  </li>
                ))}
              </ul>
            </div>
          </>
        )}

        {focus && !error && graph && activeSelection && (
          <div data-testid="node-detail">
            <h2>{activeSelection.label}</h2>
            <p>{activeSelection.is_external ? 'External reference' : 'Corpus document'}</p>
            <p>
              <Link to={`/documents/${activeSelection.id}`}>
                Open {activeSelection.label}
              </Link>
            </p>
            {activeSelection.id !== focus && (
              <button type="button" onClick={() => moveFocus(activeSelection.id)}>
                Draw the map around {activeSelection.label}
              </button>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}
