"""Generic outbound webhook notifier for agent runtimes.

When Agentira events occur (task assigned, moved, commented), this module
fires a POST to the agent's registered webhook_url in a background thread.

Payload is runtime-agnostic:
  - `message`  : human-readable string (consumed by ZeroClaw, OpenClaw, etc.)
  - structured fields: for programmatic runtimes (daemons, custom agents)

Any HTTP listener qualifies as a target — no runtime-specific coupling here.
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone

logger = logging.getLogger("agentira.notifier")


def _build_payload(event: str, task: dict, actor: str) -> dict:
    """Build the standard cross-runtime webhook payload."""
    task_id    = task.get("id", "")
    task_title = task.get("title", "")
    status     = task.get("status", "")
    priority   = task.get("priority", "")
    project_id = task.get("project_id", "")

    message = (
        f"[{event}] Task '{task_title}' (id: {task_id}) "
        f"— status: {status}, priority: {priority}. "
        f"Actor: {actor}. "
        f"Use get_task('{task_id}') for full details."
    )

    return {
        "event":      event,
        "message":    message,
        "task_id":    task_id,
        "task_title": task_title,
        "project_id": project_id,
        "status":     status,
        "priority":   priority,
        "actor":      actor,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }


def _post(url: str, payload: dict) -> None:
    """POST payload to url. Runs in background thread — never raises."""
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Webhook delivered to %s — HTTP %s", url, resp.status)
    except urllib.error.URLError as e:
        logger.warning("Webhook delivery failed (%s): %s", url, e.reason)
    except Exception as e:
        logger.warning("Webhook delivery error (%s): %s", url, e)


def notify(webhook_url: str, event: str, task: dict, actor: str) -> None:
    """Fire webhook in a background thread (non-blocking).

    Args:
        webhook_url: Target URL registered on the agent's profile.
        event:       Event type string, e.g. 'task.assigned', 'task.moved', 'task.commented'.
        task:        Task dict as returned by _task_to_dict().
        actor:       Profile name of who triggered the event.
    """
    if not webhook_url:
        return
    payload = _build_payload(event, task, actor)
    thread  = threading.Thread(target=_post, args=(webhook_url, payload), daemon=True)
    thread.start()
