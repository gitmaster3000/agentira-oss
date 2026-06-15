import os
from pathlib import Path

# All daemon state (pid, creds, logs, runs, workspaces, sources) lives under one
# home dir. Override AGENTIRA_HOME to run a SECOND, fully isolated daemon —
# e.g. a TEST daemon pointed at a local backend — alongside your main one
# without colliding on pid/credentials/logs. Read at import, so set it in the
# environment before invoking the CLI (the daemon backgrounds with the same
# env, so the child inherits it).
HOME = Path(os.environ.get("AGENTIRA_HOME") or (Path.home() / ".agentira"))
DAEMON_ID_FILE = HOME / "daemon.id"
DAEMON_PID_FILE = HOME / "daemon.pid"
DAEMON_LOG_FILE = HOME / "daemon.log"
# What the running daemon is connected to (api_url + mode) — so `status` can
# show which daemon this is (e.g. local test vs prod) when several coexist.
DAEMON_META_FILE = HOME / "daemon.meta.json"
CONFIG_FILE = HOME / "config.json"
# Admin token from `agentira daemon login` (browser-based). Mode 0600.
CREDENTIALS_FILE = HOME / "credentials.json"
WORKSPACES_DIR = HOME / "workspaces"
# AP-197: daemon-owned clones of git workspaces. The daemon clones a project's
# remote here and branches per-task worktrees off it, so it never reaches into
# the user's protected folders (~/Desktop etc., which macOS TCC blocks).
SOURCES_DIR = HOME / "sources"


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    return HOME
