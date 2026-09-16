from typing import Literal

from pydantic import BaseModel, Field, field_validator


class IngestRequest(BaseModel):
    filename: str


class SourceFileOut(BaseModel):
    """A file the Ingest screen can offer, and what ingest would make of it.

    `kind` is what `ingest_file` will treat this as, not a guess from the
    extension made here — see `sources.list_sources`. `ingested` says a
    `:Source` for this filename already exists; re-ingesting is legitimate
    (ADR-007 keeps it additive, and a second edition arrives exactly that way),
    so this informs rather than forbids.
    """

    filename: str
    size_bytes: int
    kind: str
    ingested: bool


class IngestResult(BaseModel):
    source: Literal["manifest"] = "manifest"
    nodes_created: int
    relationships_created: int
    self_references_skipped: int
    suspected_duplicates: list[list[str]] = Field(default_factory=list)


class DocumentRef(BaseModel):
    slug: str
    name: str


class DocumentIngestResult(BaseModel):
    source: Literal["document"] = "document"
    format: str
    document: DocumentRef
    nodes_created: int
    relationships_created: int
    references_attributed: int
    references_unattributed: list[str] = Field(default_factory=list)
    self_references_skipped: int
    # An ingest of a second edition creates no :Document node, so "0 nodes
    # created" is both true and unreadable. The edition and its chunk count are
    # what the reader needs in order to do the next thing.
    version_id: str
    chunks_written: int


class ResetResult(BaseModel):
    nodes_deleted: int
    relationships_deleted: int


class GraphNode(BaseModel):
    id: str
    label: str
    is_external: bool


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_nodes: int
    returned_nodes: int
    truncated: bool


type JSONScalar = str | int | float | bool
type JSONValue = JSONScalar | None | list[JSONValue] | dict[str, JSONValue]

JSON_SCALARS = (str, int, float, bool)


class QueryResult(BaseModel):
    rows: list[dict[str, JSONValue]]
    returned_rows: int
    truncated: bool


class DocumentOut(BaseModel):
    slug: str
    name: str
    is_external: bool
    references: list[str] = Field(default_factory=list)
    referenced_by: list[str] = Field(default_factory=list)
    # How many editions this document has. Zero for the great majority — an
    # externally cited document has no ingested text (STORY-040).
    version_count: int = 0


class DuplicateCandidate(BaseModel):
    """One flagged pair, with enough for a person to rule on it — STORY-031.

    A name and a slug are not enough: what a reader needs is what cites each and
    whether either carries text, because a pair where both hold editions cannot be
    merged at all (ADR-032) and the screen must say so before asking.
    """

    names: list[str]
    slugs: list[str]
    cited_by: list[int]
    has_text: list[bool]
    mergeable: bool


class MergeIn(BaseModel):
    """Which of a flagged pair survives. Names, not slugs, per ADR-032."""

    survivor: str
    merged: str


class DocumentVersionOut(BaseModel):
    version_id: str
    effective_date: str | None
    checksum: str
    source_uri: str
    supersedes: str | None

    # STORY-082. All optional, because an edition nobody has built has no build
    # to describe — and `build_state is None` is the answer that distinguishes
    # "never built" from "built and found nothing", which are the two readings an
    # obligation count of zero has and which need opposite actions.
    build_state: str | None = None
    build_run_id: str | None = None
    build_started_at: str | None = None
    build_changed_at: str | None = None
    build_extractor_adapter: str | None = None
    build_embedder_adapter: str | None = None
    build_counts: dict[str, int] = Field(default_factory=dict)
    build_error: str | None = None


class DocumentIn(BaseModel):
    name: str = Field(min_length=1)


class QueryRequest(BaseModel):
    cypher: str = Field(min_length=1)


class ChunkOut(BaseModel):
    chunk_id: str
    text: str
    page: int
    section_path: list[str]
    ordinal: int


class ObligationOut(BaseModel):
    """One obligation as a reader meets it — STORY-081.

    Deliberately the same five fields `ObligationCitationOut` carries minus the
    document name, which is redundant here: the route already names the edition.
    """

    obligation_id: str
    statement: str
    modality: str
    section_path: list[str]
    page: int


class ObligationsOut(BaseModel):
    """Bounded, and honest about it.

    `total` is the count in the graph, `returned` the count in this response.
    The largest edition in `data/samples` is 204 chunks and can produce several
    hundred obligations, so an unbounded list would be the same defect the
    document table had before STORY-070 — same idiom as `GraphOut`.
    """

    obligations: list[ObligationOut]
    total: int
    returned: int
    truncated: bool


class ObligationCitationOut(BaseModel):
    """One side of a proposed link, with enough context to decide from.

    The citation fields are not decoration: a reviewer asked whether one clause
    implements another cannot answer without knowing which document each comes
    from and where in it to go and read.

    `version_id` is part of that and was missing until the sprint-12 walkthrough.
    A proposal frequently runs between two editions of one instrument — every one
    of the 119 in the live queue did — and naming only the document then prints
    the same string on both sides of the screen. `CitationOut` on `/ask` has
    carried the edition for the same reason since it was written.
    """

    obligation_id: str
    statement: str
    modality: str
    document: str
    version_id: str
    section_path: list[str]
    page: int


class ReviewItemOut(BaseModel):
    source: ObligationCitationOut
    target: ObligationCitationOut
    confidence: float
    rationale: str
    proposer: str


class ReviewQueueOut(BaseModel):
    """The queue, and enough to say why it is empty when it is — STORY-090.

    "Nothing is waiting for review" is true of four different situations and
    tells a reader only one of them: that they are caught up. It is equally
    true when nothing has been extracted anywhere, when obligations exist in
    only one document — a proposal runs between two documents now that
    same-document pairs belong to the diff, so nothing could be proposed yet —
    and when two documents hold obligations but no `IMPLEMENTS_PROPOSED` edge
    exists, because nobody named candidates on a rebuild (or a later rebuild
    without candidates wiped the pending ones). `documents_with_obligations`
    counts distinct documents holding at least one obligation in any edition;
    a proposal is impossible below 2. Necessary and not sufficient: two
    documents whose obligations share no distinctive vocabulary clear this
    count and still propose nothing, because the proposer's floor is a
    separate condition this number says nothing about. `proposals` is the
    total of `IMPLEMENTS_PROPOSED` edges (decided or not); zero with two
    documents ready is the fourth false all-clear. Its predecessor,
    `documents_comparable`, counted documents with two obligation-holding
    editions — exactly the configuration that can no longer yield a proposal,
    so the old count had become the false all-clear STORY-090 added it to
    prevent.

    Counted here rather than derived on the screen so that two views cannot
    drift into answering the same question differently, which is the failure
    mode STORY-067 left open on Triage and this repeats.
    """

    items: list[ReviewItemOut]
    editions_with_obligations: int
    documents_with_obligations: int
    # Every `IMPLEMENTS_PROPOSED` edge, decided or not. Distinguishes "caught
    # up" (`pending == 0` with proposals still present) from "nothing was ever
    # proposed / a rebuild wiped them" (`proposals == 0`).
    proposals: int
    # Undecided proposals in the graph, not rows in `items`. The queue is capped,
    # so the two differ whenever there is real work: the screen read "Proposal 1
    # of 50" over 119 waiting, and went on reading it after every verdict because
    # deciding one refilled the page from the remainder. This is the number that
    # falls as the backlog is worked through.
    pending: int


class VerdictIn(BaseModel):
    """A reviewer's decision.

    Deliberately carries no `actor`. The actor is the authenticated principal and
    nothing else — a client-supplied one would let anyone record a decision as
    anyone, which makes the audit trail worthless. `extra="ignore"` (the default)
    means a body that sends one is accepted and the field discarded.
    """

    verdict: str = Field(min_length=1)
    rationale: str = ""


class PairingCandidateOut(BaseModel):
    """One pair of clauses the wording pass ruled on, and how it ruled.

    Both sides are full citations for `ObligationCitationOut`'s reason: the
    question is whether the newer clause is the older one reworded, and a
    reviewer cannot answer without reading both in place. `outcome` is the
    first rule that fired in the diff, in code order — `auto_paired`,
    `partner_taken`, `contested`, `below_threshold` — a precedence chain, not
    four disjoint conditions: every partner-taken pair also satisfies the
    margin predicate. `taken_by` names the auto-paired winners' other ends,
    zero to two of them, because a pair is declined when *either* endpoint was
    already consumed and the screen must say by what.
    """

    old: ObligationCitationOut
    new: ObligationCitationOut
    confidence: float
    rationale: str
    outcome: str
    taken_by: list[str]


class PairingSettledOut(BaseModel):
    """A pair a person has already ruled on, kept reachable so the verdict can
    be undone.

    Carries both citations, exactly as a candidate does, because a settled pair
    is never *also* a candidate: the diff deliberately does not re-record a
    pair a reviewer has settled, so a settled row has no entry in `items` to
    borrow its statements from — and `items` is empty in precisely the case
    this list is full. Two `distinct` verdicts between one edition pair give
    `settled=2, items=0`, at which point ids alone leave a screen with nothing
    to draw and a reviewer with no way back to a verdict they want to undo.
    Deciding whether to reverse a verdict is answering the question that was
    answered when it was made, and it needs the same two clauses in front of
    it.

    `rationale` travels for a sharper reason than completeness. Re-recording a
    verdict on the same pair SETS `rationale` unconditionally (`RECORD` in
    links/pairing.py), so a screen that cannot show the reason on record posts
    an empty one on the reviewer's behalf the moment they reverse a verdict —
    erasing the justification of the decision they are reversing, having never
    been shown it. Sent even when empty, because "" here means "recorded with
    no reason" and a missing field would mean "not asked".
    """

    old: ObligationCitationOut
    new: ObligationCitationOut
    verdict: str
    actor: str
    rationale: str


class PairingVerdictOut(BaseModel):
    """What the POST recorded, echoed back.

    Ids and not citations, and deliberately a different model from
    `PairingSettledOut`: this is the canonical `:PairingDecision` read back, and
    its job is to tell the caller which orientation the pair was stored in —
    the route reverses a newer-first request, and `pairing_key` is directional,
    so the orientation is the one thing the caller cannot infer from what it
    sent. A screen posting a verdict already holds both clauses; the queue's
    settled rows are the ones that need citations, and being drawn is their
    whole purpose.
    """

    old_id: str
    new_id: str
    verdict: str
    actor: str


class PairingQueueOut(BaseModel):
    """The pairing queue: what the diff decided, what a person settled, and
    what it could not apply.

    `pending` is undecided candidates in the graph, not rows in `items` — the
    review queue's own pattern, for its reason: the page is capped, and the
    number that falls as the backlog is worked through is the graph count.
    `pairings_unapplied` counts `paired` verdicts the diff could not apply
    because pass 1 matched the clause identically in both editions — counted,
    never dropped, so a shelved human verdict is at least visible.

    `pending_by_outcome` splits that same backlog by the diff's label, and it is
    not decoration. A declined pair scores at or below whatever beat it, so a
    confidence-ordered page cuts declines first and an unfiltered page of a
    heavily reworded edition pair shows only pairings the diff already made. The
    breakdown is what tells a reviewer a class exists before they filter to it;
    it counts the whole backlog, never the filtered page, so the number that
    justifies a filter does not disappear when the filter is applied.
    """

    items: list[PairingCandidateOut]
    settled: list[PairingSettledOut]
    pairings_unapplied: int
    pending: int
    pending_by_outcome: dict[str, int]


class PairingVerdictIn(BaseModel):
    """A reviewer's pairing verdict.

    Carries no `actor`, for `VerdictIn`'s reason: the actor is the
    authenticated principal and nothing else, and a client-supplied one would
    make the audit trail worthless.
    """

    verdict: str
    rationale: str = ""


class TriageCitationOut(BaseModel):
    """One side of a triage row, sourced. Nothing in a triage response is
    unattributed: a row naming a policy without saying which passage of it is
    affected would send a reviewer hunting.

    `version_id` is part of "sourced": the higher side comes from a diff of two
    editions of one instrument, so the document name alone matches a clause in
    each of them — the reasoning `ObligationCitationOut` and Ask's `CitationOut`
    already record, and it binds here because the two editions are on screen at
    once by construction."""

    obligation_id: str
    statement: str
    document: str
    version_id: str
    section_path: list[str]
    page: int


class TriageRowOut(BaseModel):
    change_id: str
    kind: str
    score: float
    modality: str
    summary: str
    previous_statement: str | None
    ours: TriageCitationOut
    higher: TriageCitationOut


class TriageOut(BaseModel):
    """`from_version_id` is echoed back because it may have been defaulted: a
    caller who omitted it needs to know which earlier edition the answer is about.

    `unlinked_changes` is what keeps an empty `rows` honest. Without it, "nothing
    you own is affected" and "nothing has been reviewed yet, so this cannot see
    anything" are the same response, and one of them is a false all-clear.

    `outbound_implements` is the fourth case of that false all-clear: reviewed
    `IMPLEMENTS` edges leave *this* edition pair as the implementing side. Triage
    only walks the opposite direction — something of ours IMPLEMENTS a changed
    higher obligation — so an empty table while this count is non-zero means the
    links exist and point the other way; they surface when the *other* document's
    editions are triaged.

    `pairings_unapplied` extends that discipline to the reviewer's own verdicts.
    This GET runs the diff, and the diff applies the recorded pairing decisions;
    a `paired` verdict naming a clause pass 1 has already matched as persisting
    unchanged has nothing left to bind. Reporting the number is the difference
    between a reviewer being told their decision did not land and a table that
    quietly proceeded as though it had. The verdict is untouched on disk — only
    unapplied on this pair, on this run.
    """

    from_version_id: str
    to_version_id: str
    rows: list[TriageRowOut]
    total_changes: int
    unlinked_changes: int
    pairings_unapplied: int
    # An empty `rows` has three causes, and they are not the same finding:
    # nothing is linked (unlinked_changes), nothing changed (total_changes), or
    # nothing was ever extracted. Only these two can tell the third from the
    # second, and the default `null` extractor makes the third the common case.
    from_obligations: int
    to_obligations: int
    outbound_implements: int


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class CitationOut(BaseModel):
    """Where a claim came from, precisely enough to go and read it.

    That is the whole contract, and the edition is part of it. A corpus holding
    two editions of one instrument answers questions out of both — retrieval
    searches every chunk, superseded or current — and a citation naming only
    "DoDD 5000.01, (preamble), p. 1" matches a passage in each of them. A reader
    checking whether a duty still stands cannot be handed a quotation that does
    not say which edition it was taken from (ADR-011).
    """

    document: str
    version_id: str
    section_path: list[str]
    page: int
    quote: str
    # Whether the question's own words reached this passage, rather than the
    # embedding index simply ranking it highest. A field and not only a turn of
    # phrase in `answer`, so that a caller can tell the two apart without
    # matching on English. `True` for a passage a structured template returned,
    # which was selected by naming the document.
    grounded: bool = True


class AnswerOut(BaseModel):
    """An answer and everything it rests on.

    `citations` is empty only when `answer` says the corpus does not address the
    question. An answer with no citation behind it is a hallucination with good
    grammar (ADR-017).

    There are three answer shapes, not two, and the third is deliberate. A
    question whose words appear nowhere in the corpus still returns passages —
    the closest by meaning — but the answer opens by saying so rather than with
    "The corpus states:", because a vector index ranks every chunk it holds
    against any input and so always has a top hit. The rows are evidence to
    check, not an answer, and the prose says which of the two it is. The
    distinction is in the wording only: a consumer that needs it as data should
    be given a field rather than left to match on English.
    """

    answer: str
    citations: list[CitationOut]
    template_used: str


class RebuildRequest(BaseModel):
    """What to compare the rebuilt edition against.

    Naming candidates is the only way proposals get made: nothing in the graph
    records which documents are higher-tier (ADR-015 drops tier distance from
    ranking for exactly that reason), so the caller states it and the route does
    not guess. Empty — including an omitted body — means rebuild only.
    """

    candidate_version_ids: list[str] = Field(default_factory=list)


class RebuildStarted(BaseModel):
    run_id: str
    version_id: str
    # Echoed back so the response says what the run will compare against, rather
    # than leaving the caller to infer it from an empty review queue later.
    candidate_version_ids: list[str] = Field(default_factory=list)


class RebuildStatus(BaseModel):
    """What a poller sees.

    `counts` is populated only once the run finishes and `error` only if it
    failed. Both empty, with `state` still in progress, is the normal mid-run
    reading.
    """

    run_id: str
    version_id: str
    state: str
    chunks_done: int = 0
    chunks_total: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    # Why chunks were rejected, capped. `chunks_rejected` in `counts` is the true
    # total; this says what the failures looked like. STORY-057 asked for both —
    # a count alone reports that an edition is incomplete without saying what is
    # missing from it, and reading container logs is not an answer for an operator.
    rejections: list[dict[str, str]] = Field(default_factory=list)
    # How many refusals happened, against however many `rejections` holds. The
    # list is capped; this is not, so a reader can tell the difference.
    rejections_total: int = 0
    # Which adapters the *worker* used, reported by the worker rather than read
    # off the API's own settings — the two processes are configured separately
    # and need not agree. Empty until a worker picks the run up. With the
    # default `null` extractor a run writes chunks and no obligations, which is
    # correct and looks exactly like a broken one unless the screen can say so.
    extractor_adapter: str = ""
    embedder_adapter: str = ""
    error: str | None = None
