from pathlib import Path

HOME = Path.home() / ".agentira"
DAEMON_ID_FILE = HOME / "daemon.id"
DAEMON_PID_FILE = HOME / "daemon.pid"
DAEMON_LOG_FILE = HOME / "daemon.log"
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
