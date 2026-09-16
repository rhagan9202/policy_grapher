#!/usr/bin/env bash
# What the demo will actually show, read from the running stack.
#
# The graph lives in a Docker volume that survives restarts, so anyone who
# clicks through the app changes it — approving a proposal, rebuilding an
# edition, re-ingesting a PDF. Printed numbers go stale; this re-reads them.
set -euo pipefail
cd "$(dirname "$0")/.."
TOKEN=$(grep -E '^API_TOKEN=' .env | cut -d= -f2)
H="Authorization: Bearer $TOKEN"
API=${API:-http://127.0.0.1:8000}

q() { curl -s -m 30 -X POST "$API/query" -H "$H" -H 'Content-Type: application/json' -d "{\"cypher\": $1}"; }

python3 - "$API" "$TOKEN" <<'PY'
import json, sys, urllib.request
api, token = sys.argv[1], sys.argv[2]

def get(path):
    r = urllib.request.Request(api + path, headers={"Authorization": f"Bearer {token}"})
    return json.load(urllib.request.urlopen(r, timeout=60))

def cypher(c):
    body = json.dumps({"cypher": c}).encode()
    r = urllib.request.Request(api + "/query", data=body, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=60))["rows"]

docs = get("/documents")
with_editions = [d for d in docs if d.get("version_count", 0) > 0]
queue = get("/review/queue")
obligations = cypher("MATCH (o:Obligation) RETURN count(o) AS n")[0]["n"]
links = cypher("MATCH ()-[r:IMPLEMENTS]->() RETURN count(r) AS n")[0]["n"]

print(f"documents            {len(docs)}  ({len(with_editions)} with editions)")
for d in with_editions:
    print(f"   {d['slug']:<16} {d['version_count']} edition(s)")
print(f"obligations          {obligations}")
print(f"approved links       {links}")
print(f"review queue         {queue['pending']} pending of {queue['proposals']} proposals")

print("\ntriage rows, per edition pair:")
found = False
for d in with_editions:
    versions = get(f"/documents/{d['slug']}/versions")
    for v in versions[1:]:
        t = get(f"/triage?to_version_id={v['version_id']}")
        mark = "<-- demo this" if t["rows"] else ""
        print(f"   {v['version_id']:<28} rows {len(t['rows']):<3} "
              f"unlinked {t['unlinked_changes']:<4} {mark}")
        found = found or bool(t["rows"])
if not found:
    print("   NONE. The payoff screen is empty — see 'If Triage is empty' in the runbook.")
PY
