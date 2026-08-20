#!/usr/bin/env bash
# A narrated walkthrough of what Policy Grapher can do since DI-1.
#
# Every step is a real request against a running stack — nothing here is staged.
# Start the stack first:
#
#     ./scripts/init-env.sh && docker compose up -d
#     ./scripts/demo.sh
#
# Press Enter between beats, or pass --no-pause to let it run straight through.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="${API_URL:-http://localhost:8000}"
PAUSE=1
[ "${1:-}" = "--no-pause" ] && PAUSE=0

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }
beat() { printf '\n\033[1;36m── %s\033[0m\n' "$*"; }
run()  { dim "\$ $*"; }
pause() { [ "$PAUSE" = 1 ] && { printf '\n\033[2m[Enter]\033[0m'; read -r _; } || true; }

# --- preflight ---------------------------------------------------------

[ -f "$root/.env" ] || { echo "No .env — run ./scripts/init-env.sh first." >&2; exit 1; }
API_TOKEN="$(grep -E '^API_TOKEN=' "$root/.env" | cut -d= -f2-)"
[ -n "$API_TOKEN" ] || { echo "API_TOKEN missing from .env" >&2; exit 1; }
AUTH=(-H "Authorization: Bearer $API_TOKEN")

if ! curl -sf --max-time 5 "$API/health" >/dev/null; then
  echo "Backend not answering at $API — is 'docker compose up' running?" >&2
  exit 1
fi

command -v jq >/dev/null || { echo "This script needs jq." >&2; exit 1; }

# A stale image is the demo-day landmine: `docker compose up -d` happily reuses an
# image built before this code, and the symptom is not an error — it is a backend
# that quietly behaves like DI-1. An unauthenticated request answering anything but
# 401 means the running container predates the phase 0 security gate.
probe="$(curl -s -o /dev/null -w '%{http_code}' "$API/documents")"
if [ "$probe" != "401" ]; then
  cat >&2 <<EOF
The backend at $API answered $probe to an unauthenticated request, not 401.

That means it is running an image built before the DI-2 security gate. Rebuild:

    docker compose up -d --build

(If neo4j also refuses the backend's credentials, its data volume predates the
current .env — 'docker compose down -v' recreates it; the graph re-ingests.)
EOF
  exit 1
fi

bold "Policy Grapher — what's new since DI-1"
dim  "Backend: $API   Corpus: data/samples/"
pause

# --- 1. the door is locked --------------------------------------------

beat "1. DI-1 shipped unauthenticated. That's closed."
dim "DI-1 exposed write-routed Cypher to anyone who could reach the port."
run "curl -s -o /dev/null -w '%{http_code}' $API/documents          # no token"
printf '  → \033[1m%s\033[0m\n' "$(curl -s -o /dev/null -w '%{http_code}' "$API/documents")"
run "curl -s -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer …' $API/documents"
printf '  → \033[1m%s\033[0m\n' "$(curl -s -o /dev/null -w '%{http_code}' "${AUTH[@]}" "$API/documents")"
dim "Every route but /health requires a principal — enforced by a test that walks the route table."
pause

# --- 2. clean slate ----------------------------------------------------

beat "2. Start from an empty graph"
run "curl -X POST $API/reset"
curl -s -X POST "${AUTH[@]}" "$API/reset" | jq -c .
pause

# --- 3. DI-1's capability: a citation manifest -------------------------

beat "3. DI-1's capability — ingest a citation manifest (CSV)"
run "curl -X POST $API/ingest -d '{\"filename\": \"dod_policy_references_08122026.csv\"}'"
curl -s -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"filename": "dod_policy_references_08122026.csv"}' "$API/ingest" | jq -c .
dim "A hand-built spreadsheet of citations. This is where DI-1 stopped."
pause

# --- 4. new: read an actual DoD issuance ------------------------------

beat "4. NEW — ingest an actual DoD issuance PDF"
dim "No spreadsheet. The system reads the document itself."
run "curl -X POST $API/ingest -d '{\"filename\": \"500001p_2020.pdf\"}'"
curl -s -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"filename": "500001p_2020.pdf"}' "$API/ingest" | jq .
dim "It identified itself as DoDD 5000.01 from its own cover page, and reported"
dim "which citations it could attribute and which it could not — no silent gaps."
pause

# --- 5. new: which edition did we read? -------------------------------

beat "5. NEW — the graph records WHICH EDITION it read"
run "curl $API/documents/dodd-5000-01/versions"
curl -s "${AUTH[@]}" "$API/documents/dodd-5000-01/versions" | jq .
dim "effective_date 2020-09-09 was read off the cover, not guessed and not the file date."
dim "'A policy changed' is meaningless without editions. This is the foundation for that."
pause

# --- 6. new: a later edition supersedes the earlier -------------------

beat "6. NEW — two more editions of the SAME instrument, deliberately out of order"
dim "Newest first, then oldest — the order a human would never choose."
for f in 500001p.pdf 500001p_2003.pdf; do
  run "curl -X POST $API/ingest -d '{\"filename\": \"$f\"}'"
  curl -s -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
    -d "{\"filename\": \"$f\"}" "$API/ingest" | jq -c '{document, references_attributed}'
done
run "curl $API/documents/dodd-5000-01/versions"
curl -s "${AUTH[@]}" "$API/documents/dodd-5000-01/versions" \
  | jq '[.[] | {version_id, effective_date, supersedes}]'
dim "One :Document, three editions, correctly chained 2018 → 2020 → 2022 even though"
dim "they arrived 2020, 2022, 2018. The chain is rebuilt from effective dates read off"
dim "the covers, so ingest order cannot corrupt the edition history."
pause

# --- 7. new: it refuses to guess --------------------------------------

beat "7. NEW — two different files claiming the same edition"
dim "A re-scan of a document we already hold: same cover, same date, different bytes."
cp "$root/data/samples/500001p.pdf" "$root/data/samples/_demo_rescan.pdf"
printf '\n%% rescanned copy\n' >> "$root/data/samples/_demo_rescan.pdf"
run "curl -X POST $API/ingest -d '{\"filename\": \"_demo_rescan.pdf\"}'"
curl -s -X POST "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"filename": "_demo_rescan.pdf"}' "$API/ingest" | jq -r '.detail // .'
rm -f "$root/data/samples/_demo_rescan.pdf"
dim "409, naming both checksums. The system cannot tell a better scan of one edition"
dim "from a genuine reissue — so it refuses to guess and hands the operator the decision."
pause

# --- 8. new: /query is read-only --------------------------------------

beat "8. NEW — /query is read-only, and the database enforces it"
before=$(curl -s "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"cypher": "MATCH (n) RETURN count(n) AS n"}' "$API/query" | jq '.rows[0].n')
run "curl -X POST $API/query -d '{\"cypher\": \"CREATE (:Document {slug: 0wned})\"}'"
printf '  → HTTP \033[1m%s\033[0m\n' "$(curl -s -o /dev/null -w '%{http_code}' "${AUTH[@]}" \
  -H 'Content-Type: application/json' \
  -d '{"cypher": "CREATE (:Document {slug: \"0wned\", name: \"0wned\"})"}' "$API/query")"
after=$(curl -s "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"cypher": "MATCH (n) RETURN count(n) AS n"}' "$API/query" | jq '.rows[0].n')
printf '  node count before: %s   after: %s\n' "$before" "$after"
dim "Rejected by READ routing in Neo4j itself — not by a regex over the query text."
pause

# --- 9. new: /query is bounded ----------------------------------------

beat "9. NEW — a runaway query is bounded, and says so"
run "curl -X POST $API/query -d '{\"cypher\": \"UNWIND range(1, 100000000) AS i RETURN i\"}'"
curl -s "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"cypher": "UNWIND range(1, 100000000) AS i RETURN i"}' "$API/query" \
  | jq -c '{returned_rows, truncated}'
dim "A hundred million rows, capped and reported — never silently truncated."
dim "The motivating threat: a query generated from a prompt-injected document."
pause

# --- 10. provenance ----------------------------------------------------

beat "10. Provenance — which ingest produced which document"
run "curl -X POST $API/query -d '{\"cypher\": \"MATCH (s:Source)-[:DESCRIBES]->(d) …\"}'"
curl -s "${AUTH[@]}" -H 'Content-Type: application/json' -d '{"cypher":
  "MATCH (s:Source)-[:DESCRIBES]->(d:Document) RETURN s.kind AS kind, s.filename AS file, count(d) AS documents ORDER BY documents DESC"
  }' "$API/query" | jq -c '.rows[]'
pause

# --- 11. the browser ---------------------------------------------------

beat "11. And the graph that resulted"
dim "Open http://localhost:5173 — the corpus above, rendered."
dim ""
dim "Not yet built (DI-2 phases 2-6): document text, embeddings, extracted"
dim "obligations, and impact triage itself. What you've just seen is the"
dim "substrate those are built on."
bold "End of demo."
