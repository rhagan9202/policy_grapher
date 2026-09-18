# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## The reference graph

### Document
A single policy issuance, identified by a stable slug and carrying the name it is cited by. Every node in the graph is a Document, whether the project holds its source or knows of it only because something cited it — the Corpus and External Reference distinction is a status a Document carries, not a separate kind of node.

### Reference
One Document citing another, drawn from the citing document's own references section. References are directional and carry no weight: the graph records that the citation exists, not how important it is. A document that cites itself contributes no Reference.

### Corpus
The Documents the project holds as its subject — the ones whose source was ingested and whose references were read. The Corpus is what most views mean by "the graph": it is small and legible where the full reference structure is neither.

### External reference
A Document present only because something in the Corpus cites it. Its name is known, its source is not, and nothing has been read from it — so ingesting the Corpus only ever gives it incoming References, never outgoing ones. A person may still assert an outgoing reference from it directly, and that is a legitimate state rather than corruption: asserting that an edge exists is a different act from describing a document. External references vastly outnumber the Corpus, which is why views scope to the Corpus by default rather than filtering externals out afterwards.
*Avoid:* external node, non-corpus document

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
