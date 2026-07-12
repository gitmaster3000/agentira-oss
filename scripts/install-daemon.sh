#!/usr/bin/env bash
# Agentira daemon installer — Mac + Linux.
#
# Pipeable:
#   curl -fsSL https://YOUR-INSTANCE.up.railway.app/api/public/install.sh | bash
#
# What it does:
#   1. Checks for python3 (>=3.11), claude CLI, and git
#   2. Prompts for your Agentira backend URL
#   3. pip-installs agentira-cli from that instance's published wheel
#   4. Creates ~/.agentira/.env with backend URL + API key
#   5. Prints the command to start the daemon
#
# Env vars it respects (skip interactive prompts):
#   AGENTIRA_DAEMON_API_URL  — backend URL (e.g. https://x.railway.app)
#   AGENTIRA_DAEMON_API_KEY  — your workspace API key

set -euo pipefail

# ── Visual helpers ──────────────────────────────────────────────────────
if [[ -t 1 ]]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'
    GREEN=$'\033[32m'; YELLOW=$'\033[33m'; CYAN=$'\033[36m'; NC=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; NC=""
fi

step()  { echo "${CYAN}▸${NC} ${BOLD}$*${NC}"; }
ok()    { echo "  ${GREEN}✓${NC} $*"; }
warn()  { echo "  ${YELLOW}!${NC} $*"; }
fail()  { echo "  ${RED}✗${NC} $*"; exit 1; }
hint()  { echo "    ${DIM}$*${NC}"; }

resolve_install_url() {
    local base="${1%/}"
    if ! command -v curl >/dev/null 2>&1; then
        fail "curl is required to download the CLI wheel from your Agentira instance."
    fi
    local payload
    payload=$(curl -fsS --max-time 20 "${base}/api/public/cli-release") || \
        fail "Could not fetch CLI release from ${base}/api/public/cli-release.
    Check the backend URL. The operator may need to redeploy the backend."
    python3 -c 'import json,sys; print(json.load(sys.stdin)["install_url"])' <<<"$payload"
}

echo
echo "${BOLD}Agentira daemon installer${NC}"
echo "${DIM}Mac/Linux · ~3 minutes${NC}"
echo

# ── Step 1: prerequisites ───────────────────────────────────────────────
step "Checking prerequisites"

if ! command -v python3 >/dev/null 2>&1; then
    fail "python3 not found.
    Install Python 3.11+ from https://www.python.org/downloads/
    Then re-run this installer."
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
    fail "Python $PY_VERSION found, but 3.11+ required.
    Install a newer Python from https://www.python.org/downloads/"
fi
ok "Python $PY_VERSION"

if ! command -v claude >/dev/null 2>&1; then
    warn "claude CLI not found on PATH."
    hint "Install with: npm install -g @anthropic-ai/claude-code"
    hint "(Or follow instructions at https://github.com/anthropics/claude-code)"
    hint ""
    hint "The daemon will still install, but it won't have a runtime"
    hint "to dispatch to until you install claude. You can continue if"
    hint "you'll install claude after."
    read -p "    Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        fail "Install claude first, then re-run."
    fi
else
    CLAUDE_VERSION=$(claude --version 2>&1 | head -1 || echo "unknown")
    ok "Claude CLI: $CLAUDE_VERSION"
fi

if ! command -v git >/dev/null 2>&1; then
    fail "git not found. Install from https://git-scm.com/downloads"
fi
ok "git $(git --version | awk '{print $3}')"

# ── Step 2: backend URL (needed before pip install) ─────────────────────
step "Connecting to your Agentira instance"

API_URL="${AGENTIRA_DAEMON_API_URL:-}"
if [[ -z "$API_URL" ]]; then
    echo
    echo "  ${BOLD}Backend URL${NC}"
    echo "  ${DIM}The URL of the Agentira instance you signed up at.${NC}"
    echo "  ${DIM}Example: https://agentira.up.railway.app${NC}"
    read -p "  → " API_URL
    if [[ -z "$API_URL" ]]; then
        fail "Backend URL required. Re-run when ready."
    fi
fi
API_URL="${API_URL%/}"

# ── Step 3: pip install from instance wheel ─────────────────────────────
step "Installing agentira-cli"

PIP_TARGET="$(resolve_install_url "$API_URL")"

PIP_FLAGS=""
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    PIP_FLAGS="--user"
fi

if pip3 install $PIP_FLAGS --upgrade --quiet "$PIP_TARGET"; then
    ok "agentira-cli installed from ${API_URL}"
else
    fail "pip install failed.
    Try manually: pip3 install $PIP_FLAGS '$PIP_TARGET'"
fi

if ! command -v agentira >/dev/null 2>&1; then
    warn "'agentira' command not on PATH after install."
    hint "If you used --user, add ~/.local/bin (or python's user-bin dir) to PATH:"
    hint "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    hint "  source ~/.zshrc"
    hint "Then re-run this installer."
    exit 1
fi
ok "agentira CLI on PATH: $(command -v agentira)"

# ── Step 4: API key + config ─────────────────────────────────────────────
step "Saving daemon credentials"

CONFIG_DIR="${HOME}/.agentira"
ENV_FILE="${CONFIG_DIR}/.env"
mkdir -p "$CONFIG_DIR"

API_KEY="${AGENTIRA_DAEMON_API_KEY:-}"
if [[ -z "$API_KEY" ]]; then
    echo
    echo "  ${BOLD}API key${NC}"
    echo "  ${DIM}From the website → top-right avatar → Settings → API key.${NC}"
    echo "  ${DIM}Click Reveal, then copy the hex string.${NC}"
    read -s -p "  → " API_KEY
    echo
    if [[ -z "$API_KEY" ]]; then
        fail "API key required. Re-run when ready."
    fi
fi

if [[ -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE" "${ENV_FILE}.bak.$(date +%s)"
    warn "Existing config backed up to ${ENV_FILE}.bak.*"
fi
cat > "$ENV_FILE" <<EOF
# Agentira daemon configuration.
# Generated $(date) by install-daemon.sh
#
# Edit any of these and restart the daemon to pick them up.

AGENTIRA_DAEMON_API_URL=${API_URL}
AGENTIRA_DAEMON_API_KEY=${API_KEY}
EOF
chmod 600 "$ENV_FILE"
ok "Config written to ${ENV_FILE} (mode 600)"

# ── Step 5: smoke ──────────────────────────────────────────────────────
step "Smoke-checking the backend"

if command -v curl >/dev/null 2>&1; then
    if curl -fsS --max-time 10 "${API_URL}/api/statuses" >/dev/null 2>&1; then
        ok "Backend reachable: ${API_URL}"
    else
        warn "Could not reach ${API_URL}/api/statuses"
        hint "Double-check the URL. If it's correct, the operator may be"
        hint "still provisioning the service — try again in a minute."
    fi
fi

# ── Done ───────────────────────────────────────────────────────────────
echo
echo "${GREEN}${BOLD}✓ Installed.${NC}"
echo
echo "${BOLD}Start the daemon:${NC}"
echo "  ${CYAN}agentira daemon${NC}"
echo
echo "${BOLD}Upgrade later:${NC}"
echo "  ${CYAN}agentira daemon update${NC}"
echo
echo "${BOLD}Keep it running across reboots (Mac):${NC}"
echo "  ${CYAN}agentira daemon install-service${NC}"
echo "  ${DIM}(creates a launchd plist; auto-starts at login)${NC}"
echo