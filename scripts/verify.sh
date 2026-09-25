#!/usr/bin/env bash
# What must pass before Agentira merges anything (Loop v1 C6).
# The daemon runs this on the MERGED code (project setting "Command that
# proves the project works") and pushes only on exit 0.
# Needs on the daemon host: uv, node/npm, Docker (tests use testcontainers).
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${AGENTIRA_VERIFY_VENV:-$HOME/.cache/agentira-verify/venv}"
[ -x "$VENV/bin/python" ] || uv venv -q -p 3.11 "$VENV"
VIRTUAL_ENV="$VENV" uv pip install -q -r requirements-dev.lock
VIRTUAL_ENV="$VENV" uv pip install -q --no-deps -e .

echo "verify: backend tests"
"$VENV/bin/python" -m pytest backend/tests -q -n 4 -p no:cacheprovider

echo "verify: frontend tests + build"
cd frontend
npm ci --silent --no-audit --no-fund
npx vitest run
npx vite build >/dev/null
echo "verify: OK"
