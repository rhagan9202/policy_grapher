/**
 * What every screen shows when the corpus is empty.
 *
 * ADR-019: a first run ingests nothing, so emptiness is the normal opening
 * state rather than a fault. It has to read that way — a blank screen is
 * indistinguishable from a broken one, and the audit that led here could not
 * tell, without querying Neo4j, whether Review was empty because nothing was
 * proposed or because the feature did not work.
 *
 * The message names a command and does not pretend to be a button: the ingest
 * control is STORY-043, in sprint 5. Until then this is actionable from a
 * terminal and nowhere else, which is a known and dated gap.
 */
export default function EmptyState({ lead }: { lead?: string }) {
  return (
    <div role="status" style={{ padding: '1rem 0', maxWidth: '40rem' }}>
      <p>
        <strong>{lead ? `${lead} ` : ''}No documents have been ingested yet.</strong>
      </p>
      <p>
        This is a fresh graph, not an error. Load the sample corpus by calling{' '}
        <code>POST /ingest</code> with a filename from <code>data/samples/</code> —{' '}
        <code>dod_policy_references_08122026.csv</code> for the reference manifest, or{' '}
        <code>500001p.pdf</code> for a single issuance with its text.
      </p>
    </div>
  )
}
