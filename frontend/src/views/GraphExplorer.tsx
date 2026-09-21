import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph2D, { type ForceGraphMethods, type NodeObject } from 'react-force-graph-2d'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, getGraph, listObligations, listVersions } from '../api/client'
import type {
  AssessmentState,
  DocumentVersionOut,
  FidelityTier,
  GraphNode,
  GraphOut,
  ObligationsOut,
} from '../api/types'

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

export const NODE_RELATIVE_SIZE = 5
const LABEL_FONT_SIZE = 13
/** Halo width in screen pixels; divided by zoom so it stays constant. */
const LABEL_HALO_WIDTH = 3

/** d3-force defaults are -30 and 30, which leave a neighbourhood's edges
 *  bunched into an unreadable knot. */
const CHARGE_STRENGTH = -200
export const LINK_DISTANCE = 60
/** Below this zoom, external labels are suppressed — their names run past 100
 *  characters and a dense neighbourhood collides at every one of them. */
const EXTERNAL_LABEL_ZOOM = 1.5
const RECIPROCAL_CURVATURE = 0.25

/* ---------------------------------------------------------------------------
 * U5. How much is known about a document, drawn on the node.
 *
 * Colour and size are already spent on corpus-versus-external, and R11 holds
 * motion and saturated colour back for a later change encoding. That leaves
 * shape and position, so the tier is one form repeated and counted (KTD4) and
 * the assessment state is a separate mark beside it — never a dimmer or
 * shorter version of the tier, which would fold two independent facts onto one
 * channel and make both unreadable.
 * ------------------------------------------------------------------------- */

/** Measured against every surface a mark can land on: 17.85:1 on the white
 *  canvas, 3.45:1 on the corpus fill (#2563eb) and 5.08:1 on the external fill
 *  (#7b8a9e). WCAG 1.4.11 asks 3:1 of a graphical object you must see to
 *  understand the content, and this is the darkest of the slate ramp — the next
 *  step lighter (#1e293b) measures 2.83:1 on the corpus fill and fails. Same
 *  value as LABEL_COLOUR, and for the same reason. */
const MARK_COLOUR = LABEL_COLOUR
/** Marks cross edges and neighbouring nodes exactly as labels do, so they take
 *  the label painter's halo rather than a second idea about legibility. */
const MARK_HALO_COLOUR = LABEL_HALO_COLOUR
const MARK_HALO_WIDTH = 2.5
const MARK_LINE_WIDTH = 1.8

/** Tier ticks: a fixed angular pitch from a fixed start, so the arc the ticks
 *  span grows with the tier. Counting five ticks fails at the size nodes
 *  actually render; the span stays readable after the count stops being, which
 *  is what keeps the ordinal legible zoomed out. */
const TICK_PITCH = (30 * Math.PI) / 180
const TICK_START = -Math.PI / 2
/* Mark geometry is a floor in *screen* pixels, not a fixed canvas size and not
 * a fixed screen size.
 *
 * Measured in canvas units alone, a mark shrinks with the drawing, and the zoom
 * that suppresses external labels also takes the tier marks below the size
 * anything can be counted at — which is the view the tier is needed in most,
 * because it is the one with no names left on it. Pinned to a screen size
 * instead, the marks stop growing with the node and read as an afterthought
 * stuck to the side of a large circle when someone zooms in to look at one.
 *
 * So they scale with the node while that keeps them legible, and stop shrinking
 * below the zoom where it does not. */
const TICK_GAP = 2.5
const TICK_LENGTH = 5

/** Precomputed per tier rather than derived per frame: this runs for every node
 *  on every tick of the simulation. The unit vectors, not the angles — the
 *  angles are fixed at module load, so taking their sine and cosine per node
 *  per frame was doing the same conversions thousands of times a second to
 *  arrive at the same ten numbers. */
const TIER_TICK_OFFSETS: Record<FidelityTier, { dx: number; dy: number }[]> = {
  1: [], 2: [], 3: [], 4: [], 5: [],
}
for (const tier of [1, 2, 3, 4, 5] as const) {
  for (let i = 0; i < tier; i += 1) {
    const angle = TICK_START + i * TICK_PITCH
    TIER_TICK_OFFSETS[tier].push({ dx: Math.cos(angle), dy: Math.sin(angle) })
  }
}

/* The ticks run from the top clockwise to just past the right, and the label is
 * drawn directly below. That leaves the left and the upper-left free, which is
 * where the other two marks go — the assessment badge to the left, the partial
 * mark above it. Anything placed below the node collides with the document's
 * own name at every zoom. */
const ASSESSMENT_ANGLE = Math.PI
const PARTIAL_ANGLE = (5 * Math.PI) / 4
const ASSESSMENT_DX = Math.cos(ASSESSMENT_ANGLE)
const ASSESSMENT_DY = Math.sin(ASSESSMENT_ANGLE)
const PARTIAL_DX = Math.cos(PARTIAL_ANGLE)
const PARTIAL_DY = Math.sin(PARTIAL_ANGLE)
/** Perpendicular to the partial mark's own direction, so its three dots spread
 *  across the radius rather than along the canvas x-axis. Spreading on x put
 *  the outer dot further from the node than a radial mark of the same nominal
 *  reach — on a diagonal anchor those are not the same distance — and it was
 *  that difference, not the nominal reach, that escaped the hit area. */
const PARTIAL_TANGENT_DX = -Math.sin(PARTIAL_ANGLE)
const PARTIAL_TANGENT_DY = Math.cos(PARTIAL_ANGLE)
/** Dot spacing and size, as multiples of the mark radius. */
const PARTIAL_DOT_SPREAD = 1.6
const PARTIAL_DOT_SCALE = 1 / 2.5
const PARTIAL_DOT_FACTORS = [-1, 0, 1] as const
const MARK_RADIUS = 2.6
/** Nearly touching the node: a mark floating clear of the circle reads as a
 *  second, smaller document rather than as something said about this one. */
const MARK_GAP = 1

/** The tier ladder in words. The canvas has no accessible surface of its own,
 *  so anything painted there reaches a screen reader only from this list. */
const TIER_WORDS: Record<FidelityTier, string> = {
  1: 'cited by another document only — the graph holds its name, not its text',
  2: 'in the manifest — listed, but its text has not been ingested',
  3: 'text ingested',
  4: 'obligations built',
  5: 'links reviewed',
}

/** The other axis in words. `not_assessed` covers both "no references section
 *  could be located" and "nothing was read", which are the same thing to a
 *  reader: the system cannot say what this document cites. */
const ASSESSMENT_WORDS: Record<AssessmentState, string> = {
  not_assessed: 'its own references were never read',
  assessed_cites_nothing: 'read, and cites nothing in the corpus',
  assessed_names_unresolved: 'read, with names the corpus could not resolve',
  assessed_all_resolved: 'read, and every name resolved',
}

const PARTIAL_WORDS = 'may cite more than is drawn'

/** Below this zoom the marks stop holding their screen size and shrink with the
 *  canvas again.
 *
 *  Without a floor the conversion is unbounded: at the camera's own minimum
 *  zoom a mark reaches 55 canvas units and the hit area with it, against the 60
 *  units the layout puts between two linked nodes — so a click lands on the
 *  neighbour rather than the node under the pointer. The screen-size guarantee
 *  is not worth defending down there anyway: by that zoom neighbouring nodes'
 *  marks already overlap each other, so what the floor was protecting is
 *  illegible for a different reason. 0.35 keeps the furthest mark inside
 *  LINK_DISTANCE / 2 at every zoom. */
export const MIN_MARK_SCALE = 0.35

/** At or above 1:1 the marks are plain canvas units and grow with the node;
 *  between the floor and 1:1 they hold their screen size instead of shrinking
 *  away; below the floor they shrink again rather than swallow a neighbour. */
function markGeometryScale(globalScale: number): number {
  return Math.max(Math.min(globalScale, 1), MIN_MARK_SCALE)
}

/** The radius a node's marks reach, which the pointer hit area has to match.
 *
 *  Computed from the same geometry the painter draws from, rather than from a
 *  constant maintained alongside it: a nominal reach and an actual one part
 *  company the moment a mark is anchored off-axis or spread sideways, and when
 *  they do it is a click that misses — which nothing about the drawing shows.
 *  In canvas units, so the screen-constant part is divided back out by the
 *  zoom, the same conversion the painter makes. */
function markedRadius(node: GraphNode, globalScale: number): number {
  const scale = markGeometryScale(globalScale)
  const radius = nodeRadius(node)
  const markRadius = MARK_RADIUS / scale
  const anchor = radius + MARK_GAP / scale + markRadius
  // All three marks, though at the current constants the ticks reach furthest
  // at every zoom and on both node sizes, so the other two terms never decide
  // the answer today. They are here so that changing a dot's spread or the
  // badge's size cannot quietly move a mark outside the hit area — the failure
  // this function already had once, and one no drawing reveals.
  return Math.max(
    radius + (TICK_GAP + TICK_LENGTH) / scale,
    // The triangle, not a disc: its lower corners sit further out than a badge
    // of the same radius, so bounding the round ones bounds three of the four.
    Math.hypot(anchor + markRadius, markRadius),
    Math.hypot(anchor, PARTIAL_DOT_SPREAD * markRadius) + markRadius * PARTIAL_DOT_SCALE,
  )
}

/** The library's own radius formula, `nodeRelSize * sqrt(nodeVal)`, has exactly
 *  two answers here — corpus or external — so both are taken once. */
const CORPUS_RADIUS = NODE_RELATIVE_SIZE * Math.sqrt(CORPUS_NODE_VALUE)
const EXTERNAL_RADIUS = NODE_RELATIVE_SIZE * Math.sqrt(EXTERNAL_NODE_VALUE)

function nodeRadius(node: GraphNode): number {
  return node.is_external ? EXTERNAL_RADIUS : CORPUS_RADIUS
}

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

/** Every node's neighbours, both ways along each edge.
 *
 *  Undirected on purpose, and for the same reason at both call sites: "what
 *  cites this" is as much a document's neighbourhood as "what this cites", and
 *  the walk that built the response covered both halves. Seeding a new node's
 *  position and measuring how far it sits from the focus are different
 *  questions, but they are asked of the same adjacency. */
function undirectedNeighbours(edges: GraphOut['edges']): Map<string, string[]> {
  const neighbours = new Map<string, string[]>()
  const link = (from: string, to: string) => {
    const existing = neighbours.get(from)
    if (existing) existing.push(to)
    else neighbours.set(from, [to])
  }
  for (const edge of edges) {
    link(edge.source, edge.target)
    link(edge.target, edge.source)
  }
  return neighbours
}

/** A node as the renderer holds it: our fields plus the simulation's own
 *  position and velocity, which it writes onto the object in place. The library
 *  already names that shape, so this is an alias rather than a second copy. */
type DrawnNode = NodeObject<GraphNode>

/** What an ingest that has just run says about itself, handed over by the
 *  screen that ran it. Said once, to the reader the navigation carried here —
 *  which is why it is a courtesy rather than the record: the node's own tier,
 *  assessment state and unattributed names are drawn below and outlive it. */
export type ArrivedFromIngest = {
  outcome: 'written' | 'unchanged'
  /** The document the ingest wrote, so a notice cannot outlive the address it
   *  was about. */
  slug: string
  name: string
  versionId: string
  unresolved: string[]
}

type HeldResult = {
  slug: string
  depth: number
  result: GraphOut
  data: { nodes: DrawnNode[]; links: GraphOut['edges'] }
}

const NOTHING_DRAWN = { nodes: [] as DrawnNode[], links: [] as GraphOut['edges'] }

/** What the map has read about one document, held with the slug it was read
 *  for. Two selections in flight land in whatever order the network chooses,
 *  and the panel is one surface: without the slug, a slow answer about the
 *  document you just left renders under the name of the one you are reading.
 *  Same idiom as `held` above, for the same reason.
 *
 *  `editions` is the whole answer, oldest-first, so which one is newest is read
 *  off it rather than stored beside it — a second copy of a fact is a second
 *  thing that can disagree with it. Empty means the document has no ingested
 *  edition, the common case on a focused map, where most nodes are documents
 *  the corpus holds by name because something cites them. */
type HeldNodeDetail = {
  slug: string
  /** `null` when the editions read itself failed, which is not the same fact as
   *  a document that has none — and must never render as one. Same null-versus-
   *  empty discipline the rest of this codebase uses wherever "nobody looked"
   *  and "nothing is there" share a shape. */
  editions: DocumentVersionOut[] | null
  editionsError: string | null
  obligations: ObligationsOut | null
  /** Scoped to the obligations read alone. A failure here leaves the editions
   *  standing: which editions exist is already known, and the drill-down and
   *  the one-edition message are built from that and nothing else. */
  obligationsError: string | null
}

/** Why an edition holds no obligations. A zero has several meanings and they
 *  call for opposite actions, which is the whole reason `build_state` is
 *  recorded on an edition (STORY-082): "extraction ran and found nothing" is a
 *  finding about the document, while "no build has run" is a fact about us.
 *  Rendering them the same way is the false all-clear ADR-015 exists to
 *  prevent, and R10 forbids on this screen in particular. */
function emptyObligationsReason(edition: DocumentVersionOut | undefined): string {
  if (!edition || edition.build_state == null) {
    return 'No build has run for it, so nothing has been extracted yet.'
  }
  if (edition.build_state === 'started') {
    return 'A build of it is running.'
  }
  if (edition.build_state === 'failed') {
    return 'Its last build failed, so they are missing rather than absent.'
  }
  // ADR-028: the `null` extractor writes chunks and no obligations by design,
  // so a finished run under it is not evidence about the document either.
  if (edition.build_extractor_adapter === 'null') {
    return 'It was built with the null extractor, which records none by design.'
  }
  return ''
}

/** How many obligations the panel prints before it stops. The document's own
 *  page is a link away and renders the edition in full; this is a look at what
 *  the node holds, not a second copy of that page.
 *
 *  Three rather than five, chosen against the live corpus: DoDD 5000.01's
 *  obligations run four lines each, and five of them pushed the Triage
 *  drill-down below the fold on a 900px viewport — so the panel's own bound was
 *  hiding the other half of what this unit exists to offer. The count above the
 *  list always states the edition's real total, so a smaller window costs the
 *  reader nothing they are not told about. */
const OBLIGATIONS_SHOWN = 3

/** Reference names a parse could not attribute to a document.
 *
 *  Keyed by position rather than by the name: the parser appends what it could
 *  not attribute without de-duplicating, so a references section that repeats an
 *  unparseable entry repeats it here too. Rendered in two places — beside the
 *  document just ingested, and under whichever node a reader is reading — which
 *  are the same names reaching the screen by two routes, one transient and one
 *  stored.
 */
function UnresolvedNames({ names }: { names: string[] }) {
  return (
    <ul className="node-unresolved">
      {names.map((name, index) => (
        <li key={`${index}-${name}`}>{name}</li>
      ))}
    </ul>
  )
}

export default function GraphExplorer() {
  // Focus lives in the URL, so the view is addressable, shareable, and
  // reversible by browser history (KTD5). It also supplies the back behaviour
  // the map otherwise lacks: the control that used to provide it collapsed to
  // the corpus, which is the corpus-wide affordance R12 removes.
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  // Taken once, on the mount the navigation produced, and held for this mount
  // only. An earlier draft read it straight off `useLocation()` every render
  // and said in a comment that a reload would clear it. It would not:
  // `createBrowserHistory` restores router state from `window.history.state.usr`
  // (react-router 7.18.2), which the browser keeps with the session-history
  // entry across a reload — so the sentence "Added X" would have come back
  // days later, about an ingest from another sitting. Captured here and
  // scrubbed below, the notice belongs to the arrival that caused it.
  const [arrived] = useState(
    () => (location.state as { ingest?: ArrivedFromIngest } | null)?.ingest,
  )
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

  // Take the account off the history entry once it has been read into this
  // mount. Same address, same search, so nothing refetches and the reader's
  // back button is unchanged — only the payload goes, which is what stops a
  // reload of this entry replaying a write that is no longer news.
  const navigate = useNavigate()
  useEffect(() => {
    if (!arrived) return
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
    // Once, on the mount that captured it. `arrived` never changes after that,
    // and re-running on a later search change would replace an entry the
    // reader navigated to deliberately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      const neighboursById = undirectedNeighbours(result.edges)
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
  /** How far out the drawing on screen was actually walked.
   *
   *  Not the depth in the URL: `expand` advances that synchronously, so between
   *  the click and the response every node one hop out would satisfy
   *  `hops < depth` against a drawing in which its own references were never
   *  fetched — dropping the mark below and asserting, for the length of the
   *  request, a complete neighbourhood nobody had looked for. */
  const drawnDepth = matched?.depth ?? depth
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

  // R8. What the selected document holds, read when it is selected — the
  // gesture that opens the detail, and the only one that does. Nothing here
  // touches `GET /triage`: that route runs its diff inside a write transaction,
  // so a render-time or hover-time call would write derived nodes on every
  // interaction (KTD7). The drill-down below is a link for that reason.
  const [nodeDetail, setNodeDetail] = useState<HeldNodeDetail | null>(null)
  const selectedSlug = selected?.id
  useEffect(() => {
    if (!selectedSlug) return
    let cancelled = false
    const read = async () => {
      let editions: DocumentVersionOut[]
      let newest: DocumentVersionOut | undefined
      try {
        // Two reads, not one: the obligations route takes an explicit edition
        // (STORY-081), so which edition is the newest has to be answered first.
        editions = await listVersions(selectedSlug)
        if (cancelled) return
        // Inside the guard, not after it. Anything this read hands back that is
        // not a list of editions fails here, and failing here is reported; an
        // earlier arrangement left this line outside and a malformed answer
        // threw past every branch, leaving the panel reading for ever.
        newest = editions.at(-1)
      } catch (cause: unknown) {
        if (cancelled) return
        // Nothing is known, and `editions: null` says so. Reporting `[]` here
        // would turn a failed read into the claim that this document has no
        // edition — an unknown rendered as a known-empty (R10).
        setNodeDetail({
          slug: selectedSlug,
          editions: null,
          editionsError: cause instanceof Error ? cause.message : 'Failed to read its editions.',
          obligations: null,
          obligationsError: null,
        })
        return
      }
      if (!newest) {
        // Nothing was ever ingested, so there is no edition to ask about and
        // no request to make. Asking anyway would answer for an edition that
        // does not exist.
        setNodeDetail({
          slug: selectedSlug,
          editions,
          editionsError: null,
          obligations: null,
          obligationsError: null,
        })
        return
      }
      try {
        const obligations = await listObligations(selectedSlug, newest.version_id)
        if (cancelled) return
        setNodeDetail({
          slug: selectedSlug, editions, editionsError: null, obligations, obligationsError: null,
        })
      } catch (cause: unknown) {
        if (cancelled) return
        // The editions survive. Which editions exist was already answered, and
        // the drill-down rests on that alone — losing it here would hide a
        // working control because an unrelated read failed.
        setNodeDetail({
          slug: selectedSlug,
          editions,
          editionsError: null,
          obligations: null,
          obligationsError:
            cause instanceof Error ? cause.message : 'Failed to read its obligations.',
        })
      }
    }
    void read()
    return () => {
      cancelled = true
    }
  }, [selectedSlug])

  // Keyed to the slug it was read for, like `held` above. The cleanup already
  // stops a superseded request from landing; this stops a result that did land
  // from being printed under the wrong document's name.
  const shownDetail = nodeDetail && nodeDetail.slug === selectedSlug ? nodeDetail : null
  // What the panel will actually print, against what the edition holds. Derived
  // once: the comparison and the printed number have to be the same figure, and
  // computing it twice is two places for them to stop being.
  const shownObligationCount = Math.min(
    shownDetail?.obligations?.obligations.length ?? 0,
    OBLIGATIONS_SHOWN,
  )

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

  /* How far each drawn node sits from the focused one, over the edges actually
   * returned. Read from `graph.edges` rather than `graphData.links`: the
   * simulation rewrites the copies it is given, replacing endpoint ids with
   * node objects, while the response's own edges keep their ids. */
  const hopsFromFocus = useMemo(() => {
    const hops = new Map<string, number>()
    if (!focus || !graph) return hops

    const neighbours = undirectedNeighbours(graph.edges)

    hops.set(focus, 0)
    let frontier = [focus]
    while (frontier.length) {
      const next: string[] = []
      for (const id of frontier) {
        for (const neighbour of neighbours.get(id) ?? []) {
          if (hops.has(neighbour)) continue
          hops.set(neighbour, (hops.get(id) ?? 0) + 1)
          next.push(neighbour)
        }
      }
      frontier = next
    }
    return hops
  }, [focus, graph])

  /* Whether what is drawn around this node is all of it, as far as the graph
   * holds. Two separate things make the answer no, and both have to count:
   * the budget dropped nodes somewhere in the response, or this node sits on
   * the edge of the walked radius, where the walk stopped rather than the
   * document running out of references.
   *
   * Only the *uncertain* case gets a mark. Marking the complete case instead
   * would make a missing mark an assertion that nothing more exists, which is
   * precisely the reading R10 forbids. */
  const drawnWhole = useCallback(
    (id: string) => {
      if (!graph || graph.truncated) return false
      const hops = hopsFromFocus.get(id)
      return hops !== undefined && hops < drawnDepth
    },
    [graph, hopsFromFocus, drawnDepth],
  )

  /** One mark's path, haloed then drawn, in the label painter's idiom. */
  const strokeMark = useCallback(
    (ctx: CanvasRenderingContext2D, globalScale: number, filled: boolean) => {
      ctx.strokeStyle = MARK_HALO_COLOUR
      ctx.lineWidth = MARK_HALO_WIDTH / globalScale
      ctx.lineJoin = 'round'
      ctx.stroke()
      if (filled) {
        ctx.fillStyle = MARK_COLOUR
        ctx.fill()
      } else {
        ctx.strokeStyle = MARK_COLOUR
        ctx.lineWidth = MARK_LINE_WIDTH / globalScale
        ctx.stroke()
      }
    },
    [],
  )

  const paintNode = useCallback(
    (node: DrawnNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const cx = node.x ?? 0
      const cy = node.y ?? 0
      const radius = nodeRadius(node)
      // Canvas units, floored so zooming out cannot shrink a mark on screen.
      const markScale = markGeometryScale(globalScale)
      const gap = MARK_GAP / markScale
      const tickGap = TICK_GAP / markScale
      const tickLength = TICK_LENGTH / markScale
      const markRadius = MARK_RADIUS / markScale

      // --- the tier, counted ---
      ctx.beginPath()
      for (const { dx, dy } of TIER_TICK_OFFSETS[node.fidelity_tier]) {
        ctx.moveTo(cx + dx * (radius + tickGap), cy + dy * (radius + tickGap))
        ctx.lineTo(
          cx + dx * (radius + tickGap + tickLength),
          cy + dy * (radius + tickGap + tickLength),
        )
      }
      strokeMark(ctx, globalScale, false)

      // --- the assessment state, as its own shape in its own place ---
      // Four silhouettes rather than four weights of one: hollow for "never
      // read", a bar for an explicit nothing, a triangle for names that did not
      // resolve, a solid disc for a section read clean. Absent below the third
      // tier, where `assessment_state` is null because the tier already says it.
      if (node.assessment_state) {
        const anchor = radius + gap + markRadius
        const ax = cx + ASSESSMENT_DX * anchor
        const ay = cy + ASSESSMENT_DY * anchor
        ctx.beginPath()
        if (node.assessment_state === 'assessed_cites_nothing') {
          ctx.moveTo(ax - markRadius, ay)
          ctx.lineTo(ax + markRadius, ay)
          strokeMark(ctx, globalScale, false)
        } else if (node.assessment_state === 'assessed_names_unresolved') {
          ctx.moveTo(ax, ay - markRadius)
          ctx.lineTo(ax + markRadius, ay + markRadius)
          ctx.lineTo(ax - markRadius, ay + markRadius)
          ctx.closePath()
          strokeMark(ctx, globalScale, true)
        } else {
          ctx.arc(ax, ay, markRadius, 0, 2 * Math.PI)
          strokeMark(ctx, globalScale, node.assessment_state === 'assessed_all_resolved')
        }
      }

      // --- what this node may be hiding ---
      // Three dots above and to the left of the node, clear of its name: the
      // omission must never draw the same as a document that genuinely has no
      // further references (AE6).
      if (!drawnWhole(node.id)) {
        const anchor = radius + gap + markRadius
        const px = cx + PARTIAL_DX * anchor
        const py = cy + PARTIAL_DY * anchor
        const dot = markRadius * PARTIAL_DOT_SCALE
        const spread = markRadius * PARTIAL_DOT_SPREAD
        ctx.beginPath()
        // Spread across the radius, not along the canvas x-axis: this anchor is
        // diagonal, so an x-offset carries the outer dot further from the node
        // than the same offset taken tangentially does.
        for (const factor of PARTIAL_DOT_FACTORS) {
          const ox = px + PARTIAL_TANGENT_DX * spread * factor
          const oy = py + PARTIAL_TANGENT_DY * spread * factor
          ctx.moveTo(ox + dot, oy)
          ctx.arc(ox, oy, dot, 0, 2 * Math.PI)
        }
        strokeMark(ctx, globalScale, true)
      }

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
    [drawnWhole, strokeMark],
  )

  /* The library sizes its own hit area from the node circle, and the marks sit
   * outside it — so without this a click on a node's own glyph misses it. The
   * region grows to the marks and no further: `LINK_DISTANCE` is what the
   * layout puts between two linked nodes, and a region approaching that would
   * start swallowing the neighbour instead. */
  const paintPointerArea = useCallback(
    (node: DrawnNode, colour: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
      ctx.fillStyle = colour
      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, markedRadius(node, globalScale), 0, 2 * Math.PI)
      ctx.fill()
    },
    [],
  )

  // 'after' leaves the circle itself with the library and we draw the marks and
  // the label over it. The pointer hit area is no longer the library's — the
  // marks sit outside the circle it would size, so `paintPointerArea` owns it.
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
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={paintPointerArea}
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

        {/* What the ingest that sent the reader here did, said once, where
            they landed. The map below is the durable account — this only adds
            the two things the drawing cannot say: whether this particular run
            rewrote any text, and which edition it was.

            Deliberately outside the branch that draws the neighbourhood, and
            above it. The ingest screen no longer reports a document result at
            all, so this notice is the whole account of the write; nested under
            `graph &&` it was conditional on a second, unrelated request
            succeeding, and a neighbourhood that failed to load took an
            "already present" skip and every unattributed name down with it —
            silently, since the failure on screen is about the fetch. */}
        {/* Matched on the slug against the address, not on the label against
            the drawn node: a label is missing while the node is still
            arriving, which would have made the check pass exactly when it
            could not be made. */}
        {arrived && arrived.slug === focus && (
          <div className="graph-arrival" role="status">
            <p>
              {arrived.outcome === 'unchanged'
                ? `${arrived.name} was already present. No text was rewritten, so its obligations, reviewed links and build record were left standing.`
                : `Ingested ${arrived.name}.`}{' '}
              Edition <code>{arrived.versionId}</code>.
            </p>
            {arrived.unresolved.length > 0 && (
              <>
                {/* Named, not counted. An unattributed reference is a citation
                    the graph does not hold, and a number alone says something
                    is missing without saying what. */}
                <p>
                  {arrived.unresolved.length} reference
                  {arrived.unresolved.length === 1 ? '' : 's'} in it could not be
                  attributed to a document:
                </p>
                <UnresolvedNames names={arrived.unresolved} />
              </>
            )}
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
                  {focusNode?.label ?? focus} — part of the neighbourhood, chosen by{' '}
                  {graph.truncation_basis ?? 'the render cap'}.
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

            {/* AE9. An empty or thin inbound half is partly a fact about what the
                system has not done yet.

                Note what this does not say, and what an earlier draft got wrong:
                these documents are not silent. Every one of them can be drawn
                citing something, because a manifest row names what it cites even
                when nobody has read the document itself — the backend says so at
                the query that counts them (`UNREAD_CORPUS_DOCUMENTS`). So the
                limitation is that their citations are only as complete as a
                manifest is, not that they have none. Stated only when the count
                is non-zero: a caveat printed unconditionally stops being read,
                and here it would also be false. */}
            {graph.unread_corpus_documents > 0 && (
              <p className="graph-caveat">
                {graph.unread_corpus_documents} corpus document
                {graph.unread_corpus_documents === 1 ? ' has' : 's have'} never had{' '}
                {graph.unread_corpus_documents === 1 ? 'its' : 'their'} own references
                read. What {graph.unread_corpus_documents === 1 ? 'it cites' : 'they cite'}{' '}
                is known only from {graph.unread_corpus_documents === 1 ? 'a manifest row' : 'manifest rows'}, so what
                cites this document is as complete as those rows are — and may be more
                than is drawn here.
              </p>
            )}

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
                    {/* Every mark painted on the canvas, said here. The canvas
                        is one image with one text alternative, so a mark that
                        is not a sentence in this list reaches nobody reading
                        with a screen reader. */}
                    <span className="node-facts">
                      {' — '}
                      {TIER_WORDS[node.fidelity_tier]}
                      {node.assessment_state
                        ? `; ${ASSESSMENT_WORDS[node.assessment_state]}`
                        : ''}
                      {drawnWhole(node.id) ? '' : `; ${PARTIAL_WORDS}`}
                    </span>
                    {node.unresolved_names && node.unresolved_names.length > 0 && (
                      // R7 wants the names, not a count: an unresolved public
                      // law is a different thing from an unresolved DoD
                      // issuance the corpus ought to be holding.
                      <UnresolvedNames names={node.unresolved_names} />
                    )}
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

            {/* R8, F2. Structure down to specific obligations without leaving
                the map.

                The interim shape U8 ships with, stated in the plan rather than
                assumed: obligation detail where extraction has recorded any,
                and a plain statement where it has not. Building them on demand
                waits on the managed extraction adapter, which does not exist
                yet — so this never offers an action it cannot perform. */}
            {shownDetail === null ? (
              <p>Reading what it holds…</p>
            ) : shownDetail.editions === null ? (
              /* The read failed, so nothing is known. Disjoint from the empty
                 case below by construction — `null` and `[]` are different
                 values, so no branch ordering decides which of these two
                 renders, and a reordering cannot turn a failure into the claim
                 that this document has no edition. */
              <p role="alert">
                Could not read its editions: {shownDetail.editionsError}
              </p>
            ) : shownDetail.editions.length === 0 ? (
              /* R10. The common node on a focused map, and the one a check
                 written only for the single-edition case leaves bare. The
                 corpus holds this document because something cites it, so an
                 absence here is a fact about what was never read — not a
                 finding that the document imposes nothing. */
              <p>
                <strong>
                  No edition of {activeSelection.label} has been ingested.
                </strong>{' '}
                The corpus holds its name because another document cites it, not
                its text — so there are no obligations to open, and nothing to
                compare.
              </p>
            ) : (
              <>
                {/* "Obligations", not "clauses": the word the rest of this
                    screen already uses, in the tier ladder beside every node
                    and on the document's own page. */}
                <h3>Obligations</h3>
                {shownDetail.obligationsError ? (
                  /* Said on its own line, above a drill-down that still works.
                     Which editions exist came from the other read. */
                  <p role="alert">
                    Could not read its obligations: {shownDetail.obligationsError}
                  </p>
                ) : shownDetail.obligations === null ||
                  shownDetail.obligations.total === 0 ? (
                  /* A zero has several meanings and they call for opposite
                     actions. "Extraction ran and found none" is a finding
                     about the document; "no build has run" is a fact about us,
                     and saying the second when the first is true — or the
                     reverse — is the false all-clear ADR-015 forbids. */
                  (() => {
                    const newest = shownDetail.editions.at(-1)
                    const reason = emptyObligationsReason(newest)
                    return reason === '' ? (
                      <p>
                        <strong>
                          Extraction found no obligations in edition{' '}
                          <code>{newest?.version_id}</code>.
                        </strong>
                      </p>
                    ) : (
                      <p>
                        <strong>
                          No obligations recorded for edition{' '}
                          <code>{newest?.version_id}</code>.
                        </strong>{' '}
                        {reason}
                      </p>
                    )
                  })()
                ) : (
                  <>
                    <p>
                      {shownDetail.obligations.total} obligation
                      {shownDetail.obligations.total === 1 ? '' : 's'} in edition{' '}
                      <code>{shownDetail.editions.at(-1)?.version_id}</code>.
                      {/* Two bounds can cut this list — the route's own, and
                          this panel's — so the sentence counts what is on
                          screen against what the edition holds, rather than
                          repeating either bound's idea of "returned". */}
                      {shownObligationCount < shownDetail.obligations.total && (
                        <> Showing the first {shownObligationCount}.</>
                      )}
                    </p>
                    <ol>
                      {shownDetail.obligations.obligations
                        .slice(0, OBLIGATIONS_SHOWN)
                        .map((obligation) => (
                          <li key={obligation.obligation_id}>
                            <p>{obligation.statement}</p>
                            <p>
                              <small>
                                {obligation.modality} ·{' '}
                                {obligation.section_path.join(' / ')} · p.{' '}
                                {obligation.page}
                              </small>
                            </p>
                          </li>
                        ))}
                    </ol>
                  </>
                )}

                {/* R9, KTD7. Triage is re-parented as the drill-down from a
                    document, not rebuilt inside the map: its unlinked-changes
                    guarantee is the thing ADR-015 exists to protect, and a
                    second implementation of it is a second place to lose it.

                    A link, never a fetch. The route diffs inside a write
                    transaction, so entering it is a gesture the reader makes.
                    The document is pre-filled and the edition deliberately is
                    not — pre-filling an edition would run the diff on
                    arrival, which is the same write by another route. */}
                {shownDetail.editions.length > 1 ? (
                  <p>
                    <Link to={`/triage?document=${activeSelection.id}`}>
                      Compare its editions in Triage
                    </Link>
                  </p>
                ) : (
                  /* AE7. Said where the control would have been, and distinct
                     from Triage running and reporting no changes: one is a
                     comparison that cannot be made, the other is its result. */
                  <p>
                    This document has only one edition, so there is nothing to
                    compare it against.
                  </p>
                )}
              </>
            )}

          </div>
        )}
      </aside>
    </div>
  )
}
