#!/usr/bin/env bash
#
# PreToolUse(Bash) hook: sync /docs before a real `git commit` so the doc edits
# ride along in that same commit.
#
# Why this parses the command itself instead of relying on the hook `if` filter:
# `if: "Bash(git commit*)"` FAILS OPEN on compound commands. A command such as
# `cd x && { echo hi; git status; }` — containing no `git commit` at all —
# matches it, because the matcher cannot decompose compound commands safely.
# That is harmless for a cheap script like this one, but it means the gate below
# is the real gate. Keep it deterministic.
#
# This hook never blocks a commit. Every failure path exits 0.

set -uo pipefail

# The nested session below runs git commands of its own. Do not recurse.
[ -n "${DOCS_SYNC_ACTIVE:-}" ] && exit 0

command -v jq >/dev/null 2>&1 || exit 0

cmd=$(jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
[ -z "$cmd" ] && exit 0

# Split on shell separators, then require a segment that *starts* a git commit.
# Matches: `git commit`, `cd x && git commit -m ...`, `git -C path commit`.
if ! printf '%s' "$cmd" | tr ';&|(){}' '\n\n\n\n\n\n\n' \
     | grep -Eq '^[[:space:]]*git([[:space:]]+-[cC][[:space:]]+[^[:space:]]+)*[[:space:]]+commit([[:space:]]|$)'; then
  exit 0
fi

# A dry run produces no commit, so there is nothing to document.
printf '%s' "$cmd" | grep -Fq -- '--dry-run' && exit 0

root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -d "$root/docs" ] || exit 0

# Escape hatch for testing the gate without spending a session.
if [ -n "${DOCS_SYNC_DRYRUN:-}" ]; then
  echo "docs-sync: WOULD RUN (root=$root)" >&2
  exit 0
fi

command -v claude >/dev/null 2>&1 || exit 0

read -r -d '' prompt <<'PROMPT'
A `git commit` is about to run in this repository. Bring the /docs tree in line
with the code first, so the documentation edits ride along in that same commit.

Use the `project-docs-sync` skill and follow it exactly, including its restraint
rule: most runs should produce small or no documentation edits, and "no
documentation changes needed" is a correct and complete outcome. Even on a no-op
run, update and stage the marker (docs/.doc-sync.json).

Hard constraints:
- Stage only. NEVER run `git commit`, `git push`, `git merge`, `git reset`,
  `git checkout` or `git stash`. The commit you are running ahead of will carry
  whatever you stage.
- `git add` only the specific doc paths you edited, plus docs/.doc-sync.json.
  Never `git add -A` and never `git add docs/`.
- Touch nothing outside the docs tree. Do not edit source code.

Be brief. You are running inside a pre-commit hook.
PROMPT

cd "$root" || exit 0

DOCS_SYNC_ACTIVE=1 timeout "${DOCS_SYNC_TIMEOUT:-600}" \
  claude -p "$prompt" \
    --permission-mode "${DOCS_SYNC_PERMISSION_MODE:-acceptEdits}" \
    --allowedTools "Bash(git add:*)" "Bash(git add *)" \
                   "Bash(git diff:*)" "Bash(git log:*)" "Bash(git status:*)" \
                   "Bash(git rev-parse:*)" "Bash(python3:*)" \
    --disallowedTools "Bash(git commit:*)" "Bash(git push:*)" "Bash(git merge:*)" \
                      "Bash(git reset:*)" "Bash(git checkout:*)" "Bash(git stash:*)" \
    >"${DOCS_SYNC_LOG:-/tmp/docs-sync-precommit.log}" 2>&1

exit 0
