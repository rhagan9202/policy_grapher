# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## The reference graph

### Document
A single policy issuance, identified by a stable slug and carrying the name it is cited by. Every node in the graph is a Document, whether the project holds its source or knows of it only because something cited it — the Corpus and External Reference distinction is a status a Document carries, not a separate kind of node.

### Reference
One Document citing another, drawn from the citing document's own references section. References are directional and carry no weight: the graph records that the citation exists, not how important it is. A document that cites itself contributes no Reference.

### Corpus
The Documents the project holds as its subject, as opposed to those it knows of only because something cited them. The Corpus is what most views mean by "the graph": it is small and legible where the full reference structure is neither.

Membership does not mean the document has been read. Most of the Corpus is named by a manifest, which supplies that document's citations without anything having parsed the document itself — so a Corpus document can draw References while its own Assessment state says nothing has ever been read from it.

### External reference
A Document present only because something in the Corpus cites it. Its name is known, its source is not, and nothing has been read from it — so ingesting the Corpus only ever gives it incoming References, never outgoing ones. A person may still assert an outgoing reference from it directly, and that is a legitimate state rather than corruption: asserting that an edge exists is a different act from describing a document. External references vastly outnumber the Corpus, which is why views scope to the Corpus by default rather than filtering externals out afterwards.
*Avoid:* external node, non-corpus document

### Fidelity tier
How much the system has actually done to a Document, as an ordinal: known only because something cites it, named by a manifest, text ingested, obligations built, links reviewed.

It is worked out when asked rather than recorded on the document, so it cannot drift from the graph it describes — there is no stored tier for a rebuild to leave stale.

### Assessment state
What the parser made of a Document's own references section: never read, read and citing nothing, read with some names left unresolved, or read with every name resolved.

This is a separate axis from the Fidelity tier and the two are deliberately not collapsed into one scale. A document at the top of the ladder whose references section was never located is a real state, and it must not render as one that genuinely cites nothing. The state is reported only from the tier at which the parser has actually seen the document; below that the tier is already the statement that nothing has been read, so repeating it would mark almost every Document while distinguishing none of them.

## Graph views

### Focused view
A view of one Document together with its reference neighbourhood — what it cites and what cites it — and nothing else. The neighbourhood is the whole of what a focused view may contain: documents outside it are not ranked lower, they are not candidates. This is what separates a focused view from a filtered whole-graph view, and at the Corpus's size the two would otherwise collapse into each other.

### Render cap
The ceiling on how many nodes a single graph view returns. The cap bounds what is drawn at once, never what is stored — ingestion keeps the complete reference structure regardless, and a capped view is a statement about legibility rather than about the data.

### Truncation basis
The ordering a partial view used to decide what it kept, stated in words for the reader. A flag saying a view is partial tells someone that something is missing but not what; the basis is what makes a truncated view honest rather than merely marked. Its absence is meaningful and exact: no basis means nothing was dropped, so leaving it unstated on a view that did drop something asserts completeness falsely.

## Flagged ambiguities

- "Document" covers both Corpus documents and External references; where the distinction matters, the narrower term is used rather than qualifying "document" each time.
- A Document's position relative to others — whether it is a root of the citation structure, whether that position is shared — is a fact about its References, not a property stored on it. The project settled this deliberately: such a position is derived from the graph where a caller needs it, and is defined by this project rather than reconstructed from the labels the source data carries.

## Retired

- **Reference role** — named a Document's position in the reference structure (root, sub-reference, and shared variants) as a property stored on the document itself. Removed when the project settled that position is a fact about edges rather than about a node; whether a Document belongs to the Corpus is now the only status a Document stores. Source data still carries a column of such labels, so the term is still met when reading corpus input — but it describes the input, not the graph.
