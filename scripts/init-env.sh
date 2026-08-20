#!/usr/bin/env bash
# Generate a local .env with random secrets. Safe to re-run: refuses to overwrite.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="$root/.env"

if [ -e "$target" ]; then
  echo "$target already exists — delete it first if you want fresh secrets." >&2
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
