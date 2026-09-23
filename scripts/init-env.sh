#!/usr/bin/env bash
# Generate a local .env with random secrets. Safe to re-run: refuses to overwrite.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/.env"

if [ -e "$target" ]; then
  echo "$target already exists — delete it first if you want fresh secrets." >&2
  exit 1
fi

# A new password against a database that already exists is always an auth
# failure, never a maybe. Neo4j reads NEO4J_AUTH only while initialising an empty
# data directory; once the volume holds /data/dbms/auth.ini the stored password
# wins and the variable is ignored, silently, on every later start. So writing a
# fresh .env beside a surviving neo4j-data volume guarantees a stack that cannot
# authenticate — and does it where the evidence points the wrong way, because
# `docker compose config` shows the new password and the neo4j container reports
# healthy (its healthcheck is HTTP-only by design).
#
# Refusing rather than warning, for two reasons: a warning printed here scrolls
# past tens of minutes of image pulls before the failure appears, and there is no
# case where a freshly generated random password matches an existing volume.
project="${COMPOSE_PROJECT_NAME:-$(basename "$root" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}"
volume="${project}_neo4j-data"
if [ -z "${INIT_ENV_ALLOW_STALE_VOLUME:-}" ] \
   && command -v docker >/dev/null 2>&1 \
   && docker volume inspect "$volume" >/dev/null 2>&1; then
  cat >&2 <<REFUSAL
Refusing to write $target: the Neo4j volume "$volume" already exists.

That volume holds a database initialised with a password this script is about to
replace. Neo4j only reads NEO4J_AUTH when it initialises an empty data
directory, so the stored password would win and the new one in .env would be
ignored — and every check you would run afterwards would say the configuration
is correct, because it is. Only authentication would disagree.

If the graph is disposable, drop it and run this again:

    docker compose down -v
    ./scripts/init-env.sh

If it is not, recover the .env that initialised that volume instead; the stored
password is hashed and cannot be read back out.

To proceed anyway — you have a matching password to paste in by hand:

    INIT_ENV_ALLOW_STALE_VOLUME=1 ./scripts/init-env.sh
REFUSAL
  exit 1
fi

password="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
token="$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)"
digest="$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)"

sed -e "s|__NEO4J_PASSWORD__|$password|g" -e "s|__API_TOKENS__|dev:$digest|g" \
    -e "s|__API_TOKEN__|$token|g" \
    "$root/.env.example" > "$target"

echo "Wrote $target"
echo "Your API token (not stored anywhere else — save it now): $token"
