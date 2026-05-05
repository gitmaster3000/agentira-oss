from pathlib import Path

HOME = Path.home() / ".agentira"
DAEMON_ID_FILE = HOME / "daemon.id"
DAEMON_PID_FILE = HOME / "daemon.pid"
DAEMON_LOG_FILE = HOME / "daemon.log"
CONFIG_FILE = HOME / "config.json"
WORKSPACES_DIR = HOME / "workspaces"


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    return HOME
