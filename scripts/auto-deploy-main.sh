#!/bin/bash
# Keep the local Docker stack (http://localhost:3113) on the latest origin/main.
#
#   scripts/auto-deploy-main.sh install     one-time setup: dedicated clone + launchd job (macOS)
#   scripts/auto-deploy-main.sh uninstall   remove the launchd job
#   scripts/auto-deploy-main.sh             one check-and-deploy pass (what launchd runs)
#
# Builds from its own clone (~/.agentira-deploy/agentira-oss), never from your working
# checkout, so branches and uncommitted work stay untouched.
set -u
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin
D="${AGENTIRA_DEPLOY_DIR:-$HOME/.agentira-deploy}"; REPO="$D/agentira-oss"; LOCK="$D/lock"
LABEL=com.agentira.autodeploy; PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
log() { echo "$(date '+%F %T') $*"; }

install() {
  SRC="$(cd "$(dirname "$0")/.." && pwd)"
  mkdir -p "$D/logs"
  [ -d "$REPO/.git" ] || git clone -q "$(git -C "$SRC" remote get-url origin)" "$REPO" || exit 1
  # Untracked local config the stack needs: COMPOSE_FILE, ports, VITE_CONNECTED_APPS.
  cp "$SRC/.env" "$SRC/docker-compose.local.yml" "$REPO/" || exit 1
  cp "$SELF" "$D/auto-deploy.sh"
  cat >"$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>$LABEL</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>$D/auto-deploy.sh</string></array>
<key>StartInterval</key><integer>120</integer>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>$D/logs/deploy.log</string>
<key>StandardErrorPath</key><string>$D/logs/deploy.log</string>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$PLIST" && log "installed; log: $D/logs/deploy.log"
}

uninstall() {
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; rm -f "$PLIST"; log "removed $LABEL"
}

deploy() {
  mkdir "$LOCK" 2>/dev/null || { [ -n "$(find "$LOCK" -mmin +30 2>/dev/null)" ] && rmdir "$LOCK"; exit 0; }
  trap 'rmdir "$LOCK"' EXIT
  cd "$REPO" || exit 1
  git fetch -q origin main || { log "fetch failed"; exit 1; }
  NEW=$(git rev-parse origin/main); OLD=$(cat "$D/deployed-sha" 2>/dev/null || true)
  UP=$(docker ps -q --filter "label=com.docker.compose.project.working_dir=$REPO" --filter name=frontend | head -1)
  [ "$NEW" = "$OLD" ] && [ -n "$UP" ] && exit 0
  if [ -n "$(ls -A "$HOME/.agentira/inflight" 2>/dev/null)" ]; then
    log "agent runs in flight, deferring ${NEW:0:8}"; exit 0
  fi
  log "deploying ${OLD:0:8} -> ${NEW:0:8}"
  git checkout -q --detach origin/main && git reset -q --hard origin/main || exit 1
  docker compose -p agentira-oss up -d --build backend mcp frontend >>"$D/logs/build.log" 2>&1 \
    || { log "build failed, see $D/logs/build.log"; exit 1; }
  for _ in $(seq 1 60); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3113/)" = 200 ]; then
      echo "$NEW" >"$D/deployed-sha"; log "deployed ${NEW:0:8}"; exit 0
    fi
    sleep 3
  done
  log "built ${NEW:0:8} but :3113 not healthy"; exit 1
}

case "${1:-}" in
  install) install ;;
  uninstall) uninstall ;;
  *) deploy ;;
esac
