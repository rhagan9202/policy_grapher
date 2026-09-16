"""Which of our obligations plausibly implements which higher-level one.

Deliberately cheap. This is lexical overlap plus shared issuance designators — no
model, no embeddings. Phase 6's hybrid retrieval will do better, and this phase
does not need better: a weak proposer behind a human gate is safe in a way a
strong proposer without one is not. What matters here is that every proposal is
*explainable* — a reviewer sees exactly what the two clauses have in common — and
that a proposal can never be mistaken for a decision (`propose_links` writes only
`IMPLEMENTS_PROPOSED`, and nothing in this module can write `IMPLEMENTS`).

Two questions share the one measure. `score_pair` words its rationale for the
implements reviewer and `score_pairing` for the pairing reviewer — same overlap,
same floor, different closing sentence, because a rationale is advice to a
specific person about a specific question.
"""

import re
from dataclasses import dataclass

from neo4j import ManagedTransaction

# "DoDI 5000.88", "DoDD 5000.01", "DoDM 8180.01" in running prose. The reference
# parser in sources/pdf.py anchors to a whole reference-list entry, which never
# matches a citation embedded mid-sentence — which is where an obligation cites.
DESIGNATOR = re.compile(r"\bDoD[DIM]\s+[0-9][0-9.\-]*[A-Z]?\b")

WORD = re.compile(r"[a-z][a-z\-]{2,}")

# Words carried by nearly every obligation in a policy corpus. Counting them as
# overlap makes every clause look related to every other, which is the failure
# mode that would flood the review queue with noise and get it ignored.
STOPWORDS = frozenset(
    ["the", "and", "for", "that", "with", "this", "from", "will", "shall", "must", "should", "may", "any", "all", "not", "are", "was", "were", "been", "being", "have", "has", "had", "its", "their", "they", "them", "which", "when", "where", "who", "whom", "such", "other", "than", "then", "there", "these", "those", "upon", "under", "over", "into", "onto", "out", "off", "each", "every", "both", "either", "neither", "about", "after", "before", "during", "within", "without", "accordance", "applicable", "appropriate", "required", "requirement", "requirements", "ensure", "ensures", "provide", "provides", "provided", "including", "include", "includes", "issuance", "department", "defense", "dod", "component", "components", "section", "subsection", "paragraph"]
)

MIN_CONFIDENCE = 0.30
DESIGNATOR_WEIGHT = 0.25


@dataclass(frozen=True)
class Candidate:
    confidence: float
    # The full sentence for the reviewer this scorer serves: the facts below,
    # plus that reviewer's own closing question.
    rationale: str
    # The same facts without the question. A consumer showing this to a
    # *different* reader takes these instead — the diff's `:Change` summary is
    # read on Triage by a compliance analyst, and the pairing reviewer's open
    # question is not theirs to answer.
    facts: str


def designators(text: str) -> set[str]:
    """Issuance designators cited anywhere in the text."""
    return {re.sub(r"\s+", " ", m) for m in DESIGNATOR.findall(text)}


def content_words(text: str) -> set[str]:
    """The words worth comparing: lowercase, three letters or more, no stopwords."""
    return {w for w in WORD.findall(text.casefold()) if w not in STOPWORDS}


def _score(
    a_statement: str, b_statement: str
) -> tuple[float, set[str], set[str], float] | None:
    """The measurement both scorers share: (confidence, shared words, shared
    designators, overlap), or None when a statement has no content words or the
    confidence is under `MIN_CONFIDENCE`. Symmetric, so argument order carries
    no meaning here — each caller's signature says which end is which.

    Overlap is measured against the *shorter* statement's vocabulary rather
    than the union: a short clause wholly contained in a long one is the normal
    shape for both questions, and a Jaccard denominator would score exactly
    that case as unrelated.
    """
    a_words = content_words(a_statement)
    b_words = content_words(b_statement)
    if not a_words or not b_words:
        return None

    shared_words = a_words & b_words
    overlap = len(shared_words) / min(len(a_words), len(b_words))
    shared_designators = designators(a_statement) & designators(b_statement)

    confidence = min(1.0, overlap + DESIGNATOR_WEIGHT * len(shared_designators))
    if confidence < MIN_CONFIDENCE:
        return None
    return confidence, shared_words, shared_designators, overlap


def _facts(shared_words: set[str], shared_designators: set[str], overlap: float) -> str:
    """What was actually matched, for a human about to decide — never a claim
    that the pair is correct, which is the reviewer's call. Each scorer appends
    its own closing sentence naming its reviewer's question."""
    terms = ", ".join(sorted(shared_words)[:6]) or "no distinctive terms"
    cites = (
        f"Both cite {', '.join(sorted(shared_designators))}; "
        if shared_designators
        else ""
    )
    return (
        f"{cites}they share {overlap:.0%} of the shorter clause's distinctive "
        f"wording ({terms})."
    )


def score_pair(org_statement: str, higher_statement: str) -> Candidate | None:
    """How plausibly the org clause implements the higher one, or None if not.

    The closing sentence is byte-for-byte what it was before `_facts` was split
    out, and a test pins it: this string is persisted on every proposal, so a
    rewording here silently rewrites what live review queues say.
    """
    scored = _score(org_statement, higher_statement)
    if scored is None:
        return None
    confidence, shared_words, shared_designators, overlap = scored
    facts = _facts(shared_words, shared_designators, overlap)
    return Candidate(
        confidence=confidence,
        rationale=(
            facts
            + " Confirm the org clause actually discharges the higher duty "
            "before approving."
        ),
        facts=facts,
    )


def score_pairing(after_statement: str, before_statement: str) -> Candidate | None:
    """How plausibly the newer clause is the older one reworded, or None if not.

    The same measure and floor as `score_pair` — one `_score`, so the two
    cannot drift — with a different sentence, because the reviewer's question
    is different. An implements advisory here would tell a pairing reviewer to
    verify a relationship nobody is claiming.
    """
    scored = _score(after_statement, before_statement)
    if scored is None:
        return None
    confidence, shared_words, shared_designators, overlap = scored
    facts = _facts(shared_words, shared_designators, overlap)
    return Candidate(
        confidence=confidence,
        rationale=(
            facts
            + " The question is whether the newer clause is the older one "
            "reworded."
        ),
        facts=facts,
    )


READ_OBLIGATIONS = """
MATCH (d:Document)-[:HAS_VERSION]->(v:DocumentVersion)-[:MANDATES]->(o:Obligation)
WHERE v.version_id IN $version_ids
RETURN o.obligation_id AS id,
       o.statement     AS statement,
       d.slug          AS document_slug
"""

WRITE_PROPOSALS = """
UNWIND $proposals AS p
MATCH (source:Obligation {obligation_id: p.source})
MATCH (target:Obligation {obligation_id: p.target})
MERGE (source)-[r:IMPLEMENTS_PROPOSED]->(target)
SET r.confidence = p.confidence,
    r.rationale  = p.rationale,
    r.proposer   = p.proposer
"""


def propose_links(
    tx: ManagedTransaction,
    *,
    org_version_id: str,
    candidate_version_ids: list[str],
    proposer: str,
) -> int:
    """Propose which obligation of `org_version_id` implements which of the
    candidates. Returns how many proposals were written.

    Writes `IMPLEMENTS_PROPOSED` and nothing else. `IMPLEMENTS` has exactly one
    writer — `decisions.replay_decisions` — and this is deliberately not it.
    Pairs whose obligations share a document are not proposed at all: between
    two editions of one instrument the question is pairing, not implementation,
    and the diff asks it.
    """
    ours = list(tx.run(READ_OBLIGATIONS, {"version_ids": [org_version_id]}))
    theirs = list(tx.run(READ_OBLIGATIONS, {"version_ids": candidate_version_ids}))
    if not ours or not theirs:
        return 0

    proposals = []
    for org in ours:
        for higher in theirs:
            # A version named as its own candidate would otherwise link every
            # clause to itself at confidence 1.0 and swamp the queue.
            #
            # Subsumed by the document check below, and no test can kill this
            # line: a :DocumentVersion has exactly one parent :Document, so
            # every self-pair is also a same-document pair and the check below
            # reaches it either way. Kept because the two guard different
            # failures and only coincidentally agree today — that one decides
            # which documents may be linked at all, this one that a clause is
            # not evidence for itself. Narrowing the document rule, which is
            # the kind of change this design makes, brings the self-pair back
            # at confidence 1.0 and puts it at the top of a reviewer's queue
            # with nothing to catch it.
            if org["id"] == higher["id"]:
                continue
            # Two editions of one instrument are the pairing question — is the
            # newer clause the older one reworded? — and that question has its
            # own decision node and its own queue. An IMPLEMENTS between them
            # asserts that a document discharges its own predecessor, which is
            # the claim the sprint-12 walkthrough found scored at the top of
            # Triage.
            if org["document_slug"] == higher["document_slug"]:
                continue
            candidate = score_pair(org["statement"], higher["statement"])
            if candidate is None:
                continue
            proposals.append(
                {
                    "source": org["id"],
                    "target": higher["id"],
                    "confidence": candidate.confidence,
                    "rationale": candidate.rationale,
                    "proposer": proposer,
                }
            )

    if proposals:
        tx.run(WRITE_PROPOSALS, {"proposals": proposals}).consume()
    return len(proposals)
