#!/usr/bin/env bash
#
# Automatic LOCAL PR preview (AP-290) — zero cloud cost.
#
# Driven by a self-hosted GitHub Actions runner on your machine (see
# .github/workflows/local-preview.yml). For each open PR it serves the branch
# from a dedicated git worktree in its own Vite dev container, proxying /api to
# your LOCAL backend (the docker stack on :8111, which uses local Postgres for
# prod parity). Tears the preview down when the PR closes.
#
# One preview per PR, on a deterministic localhost port, so several PRs can be
# previewed at once without clobbering each other or your main checkout.
#
# Usage:
#   scripts/local-pr-preview.sh up   <PR_NUMBER> <BRANCH>
#   scripts/local-pr-preview.sh down <PR_NUMBER>

set -euo pipefail

ACTION="${1:?usage: local-pr-preview.sh up <PR> <BRANCH> | down <PR>}"
PR="${2:?PR number required}"

REPO_DIR="$(git rev-parse --show-toplevel)"
WORKTREE="$REPO_DIR/.preview/pr-$PR"
NAME="agentira-preview-pr-$PR"
PORT=$((3200 + PR % 700))                       # deterministic per-PR host port
IMAGE="agentira-frontend-dev"
BACKEND="http://host.docker.internal:8111"      # local backend, from inside the container

teardown() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  git -C "$REPO_DIR" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
}

case "$ACTION" in
  down)
    teardown
    echo "torn down preview for PR #$PR"
    ;;
  up)
    BRANCH="${3:?branch required for 'up'}"
    git -C "$REPO_DIR" fetch origin "$BRANCH" --quiet
    teardown                                    # drop any stale preview first
    git -C "$REPO_DIR" worktree add --force --detach "$WORKTREE" "origin/$BRANCH" >/dev/null
    # Build the dev image (cached after the first run, so this is fast).
    docker build -q -f "$REPO_DIR/Dockerfile.dev" -t "$IMAGE" "$REPO_DIR" >/dev/null
    # Serve the worktree with HMR; anonymous /app/node_modules keeps the image's
    # npm ci output (host has none). /api → local backend.
    docker run -d --name "$NAME" -p "$PORT:3111" \
      -v "$WORKTREE:/app" -v /app/node_modules \
      -e VITE_PROXY_TARGET="$BACKEND" \
      "$IMAGE" >/dev/null
    echo "PREVIEW_URL=http://localhost:$PORT"
    ;;
  *)
    echo "usage: local-pr-preview.sh up <PR> <BRANCH> | down <PR>"; exit 1;;
esac
