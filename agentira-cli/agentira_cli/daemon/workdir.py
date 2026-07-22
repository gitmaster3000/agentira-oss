"""Per-task isolated working directories with GC.

Mirrors multica/server/internal/daemon/execenv/execenv.go.
Each task gets ~/.agentira/workspaces/<workspace_id>/<task_id>/workdir/
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path

from agentira_cli.state.paths import WORKSPACES_DIR, ensure_home

logger = logging.getLogger("agentira.daemon.workdir")

_GC_INTERVAL = 3600       # 1 hour
_TTL = 86400              # 24 hours — completed task dirs
_ORPHAN_TTL = 3 * 86400  # 72 hours — dirs with no .gc_meta.json


def task_workdir(workspace_id: str, task_id: str) -> Path:
    """Return (and create) the workdir for a task."""
    ensure_home()
    d = WORKSPACES_DIR / workspace_id / task_id / "workdir"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mark_complete(workspace_id: str, task_id: str) -> None:
    """Write .gc_meta.json so GC knows when the task finished."""
    import json
    import time as _time
    meta = WORKSPACES_DIR / workspace_id / task_id / ".gc_meta.json"
    meta.write_text(json.dumps({"completed_at": _time.time()}))


class WorkdirGC:
    """Background thread that prunes old task workdirs."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="workdir-gc", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(timeout=_GC_INTERVAL):
            self._run()

    def _run(self) -> None:
        import json
        now = time.time()
        if not WORKSPACES_DIR.exists():
            return
        for ws_dir in WORKSPACES_DIR.iterdir():
            if not ws_dir.is_dir():
                continue
            for task_dir in ws_dir.iterdir():
                if not task_dir.is_dir():
                    continue
                meta_path = task_dir / ".gc_meta.json"
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text())
                        completed_at = meta.get("completed_at", 0)
                        if now - completed_at > _TTL:
                            shutil.rmtree(task_dir, ignore_errors=True)
                            logger.debug("GC: removed %s", task_dir)
                    except Exception:
                        pass
                else:
                    # No meta — use dir mtime as proxy
                    try:
                        if now - task_dir.stat().st_mtime > _ORPHAN_TTL:
                            shutil.rmtree(task_dir, ignore_errors=True)
                            logger.debug("GC: removed orphan %s", task_dir)
                    except Exception:
                        pass
