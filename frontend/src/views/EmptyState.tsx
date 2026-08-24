import { Link } from 'react-router-dom'

/**
 * What every screen shows when the corpus is empty.
 *
 * ADR-019: a first run ingests nothing, so emptiness is the normal opening
 * state rather than a fault. It has to read that way — a blank screen is
 * indistinguishable from a broken one, and the audit that led here could not
 * tell, without querying Neo4j, whether Review was empty because nothing was
 * proposed or because the feature did not work.
 *
 * It now offers the screen that fixes it. This component used to say "the
 * ingest control is STORY-043, in sprint 5 — until then this is actionable from
 * a terminal and nowhere else, which is a known and dated gap". STORY-043
 * landed; naming an endpoint while a screen sits one click away in the
 * navigation would be that gap reopened as prose. The endpoint stays named
 * because someone driving the API still needs it.
 */
export default function EmptyState({ lead }: { lead?: string }) {
  return (
    <div role="status" style={{ padding: '1rem 0', maxWidth: '40rem' }}>
      <p>
        <strong>{lead ? `${lead} ` : ''}No documents have been ingested yet.</strong>
      </p>
      <p>
        This is a fresh graph, not an error. <Link to="/ingest">Ingest a document</Link>{' '}
        to get started — <code>dod_policy_references_08122026.csv</code> for the
        438-document reference manifest, or <code>500001p.pdf</code> for a single
        issuance with its text. Both ship in <code>data/samples/</code>.
      </p>
      <p>
        From the API that is <code>POST /ingest</code> with a <code>filename</code>.
      </p>
    </div>
  )
}
