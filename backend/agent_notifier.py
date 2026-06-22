"""Outbound webhook dispatch layer for agent runtimes.

Fires structured POST payloads to registered agent webhook URLs when
Agentira events occur (task assigned, moved, commented, etc.).

Payload contract — structured fields only, no freeform message:
  Task events:    event, task_id, task_title, project_id, status, priority, actor, timestamp
  Project events: event, project_id, project_name, actor, timestamp

Prompt injection defence: task/project titles are user-supplied content.
Pre-composing them into a freeform string and sending to an LLM is a
prompt injection vector. Receivers construct their own sanitised context
from structured fields.

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

# ── Default subscription rules ────────────────────────────────────────────
# Applied when project.webhook_config is NULL.
# Changing defaults is a code deploy, not a DB migration.

DEFAULT_WEBHOOK_RULES: list[dict] = [
    {"event": "task.assigned",      "receivers": "assignee"},
    {"event": "task.moved",         "receivers": "assignee"},
    {"event": "task.commented",     "receivers": "assignee"},
    {"event": "task.created",       "receivers": "bots"},
    {"event": "task.updated",       "receivers": "assignee"},
    {"event": "project.updated",    "receivers": "bots"},
    {"event": "project.member.add", "receivers": "assignee"},
]

# ── Payload builders ─────────────────────────────────────────────────────

def _build_payload(event: str, task: dict, actor: str) -> dict:
    return {
        "event":      event,
        "task_id":    task.get("id", ""),
        "task_title": task.get("title", ""),
        "project_id": task.get("project_id", ""),
        "status":     task.get("status", ""),
        "priority":   task.get("priority", ""),
        "actor":      actor,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }


def _build_project_payload(event: str, project: dict, actor: str) -> dict:
    return {
        "event":        event,
        "project_id":   project.get("id", ""),
        "project_name": project.get("name", ""),
        "actor":        actor,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }


# ── HTTP delivery ────────────────────────────────────────────────────────

def _post(url: str, payload: dict, token: str = "") -> None:
    """POST payload to url. Runs in background thread — never raises."""
    try:
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req  = urllib.request.Request(
            url, data=data,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info("Webhook delivered to %s — HTTP %s", url, resp.status)
    except urllib.error.URLError as e:
        logger.warning("Webhook delivery failed (%s): %s", url, e.reason)
    except Exception as e:
        logger.warning("Webhook delivery error (%s): %s", url, e)


# ── Transport resolution ─────────────────────────────────────────────────

def resolve_transport(profile) -> str:
    """Return the effective notification transport for a profile.

    Resolution order:
      1. profile.notification_transport (explicit always wins)
      2. 'webhook' if profile.webhook_url is set
      3. 'poll'    (safe default — agent pulls on its own schedule)
    """
    if profile.notification_transport:
        return profile.notification_transport
    if profile.webhook_url:
        return "webhook"
    return "poll"


# ── Webhook target resolution ────────────────────────────────────────────

def get_webhook_targets(db, project_id: str, event: str, assignee_name: str) -> list:
    """Return profiles that should receive a webhook for this event.

    Loads project.webhook_config (JSON) or falls back to DEFAULT_WEBHOOK_RULES.
    Resolves receiver groups → profiles → filters to webhook transport only.

    Args:
        db:            SQLAlchemy session.
        project_id:    Project where the event occurred.
        event:         Event string, e.g. 'task.moved'.
        assignee_name: Current assignee of the task (may be empty string).

    Returns:
        List of Profile ORM objects whose resolved transport is 'webhook'.
    """
    from backend.models import Project, ProjectMember, Profile

    project = db.get(Project, project_id)
    if not project:
        return []

    # Determine rules to apply
    rules = DEFAULT_WEBHOOK_RULES
    if project.webhook_config:
        try:
            cfg = json.loads(project.webhook_config)
            if not cfg.get("enabled", True):
                return []
            rules = cfg.get("rules", DEFAULT_WEBHOOK_RULES)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Invalid webhook_config JSON for project %s — using defaults", project_id)

    # Find receiver group for this event
    receiver_group = None
    for rule in rules:
        if rule.get("event") == event:
            receiver_group = rule.get("receivers")
            break
    if receiver_group is None:
        return []

    # Resolve receiver group → profiles
    targets: list = []
    if receiver_group == "assignee":
        if assignee_name:
            prof = db.query(Profile).filter(Profile.name == assignee_name).first()
            if prof:
                targets = [prof]
    elif receiver_group == "bots":
        targets = (
            db.query(Profile)
            .join(ProjectMember, ProjectMember.profile_id == Profile.id)
            .filter(ProjectMember.project_id == project_id,
                    Profile.account_type != "human")
            .all()
        )
    elif receiver_group == "members":
        targets = (
            db.query(Profile)
            .join(ProjectMember, ProjectMember.profile_id == Profile.id)
            .filter(ProjectMember.project_id == project_id)
            .all()
        )

    # Filter to webhook-transport profiles only
    return [p for p in targets if resolve_transport(p) == "webhook"]


# ── Dispatch API ─────────────────────────────────────────────────────────

def dispatch(db, event: str, task: dict, actor: str) -> None:
    """Config-driven fan-out dispatch for task-level events.

    Resolves webhook targets from project.webhook_config (or defaults),
    then fires one background POST per target. Non-blocking.

    Args:
        db:    SQLAlchemy session (read-only — no writes).
        event: Event string, e.g. 'task.moved'.
        task:  Task dict as returned by services._task_to_dict().
        actor: Profile name of who triggered the event.
    """
    project_id    = task.get("project_id", "")
    assignee_name = task.get("assignee", "")
    targets = get_webhook_targets(db, project_id, event, assignee_name)

    if not targets:
        return

    # Extract auth token from project webhook_config
    token = ""
    from backend.models import Project
    project = db.get(Project, project_id)
    if project and project.webhook_config:
        try:
            cfg = json.loads(project.webhook_config)
            token = cfg.get("token", "")
        except (json.JSONDecodeError, AttributeError):
            pass

    payload = _build_payload(event, task, actor)
    for profile in targets:
        thread = threading.Thread(
            target=_post, args=(profile.webhook_url, payload, token), daemon=True
        )
        thread.start()
        logger.debug("Dispatched %s webhook to %s", event, profile.name)


def dispatch_project(db, event: str, project: dict, actor: str) -> None:
    """Config-driven fan-out dispatch for project-level events.

    Uses 'assignee' param as empty string (no task assignee for project events).
    """
    project_id = project.get("id", "")
    targets    = get_webhook_targets(db, project_id, event, assignee_name="")

    if not targets:
        return

    # Extract auth token from project webhook_config
    token = ""
    from backend.models import Project as ProjectModel
    proj_obj = db.get(ProjectModel, project_id)
    if proj_obj and proj_obj.webhook_config:
        try:
            cfg = json.loads(proj_obj.webhook_config)
            token = cfg.get("token", "")
        except (json.JSONDecodeError, AttributeError):
            pass

    payload = _build_project_payload(event, project, actor)
    for profile in targets:
        thread = threading.Thread(
            target=_post, args=(profile.webhook_url, payload, token), daemon=True
        )
        thread.start()
        logger.debug("Dispatched %s webhook to %s", event, profile.name)


# ── Legacy single-target API (kept for backward compat) ──────────────────

def notify(webhook_url: str, event: str, task: dict, actor: str) -> None:
    """Fire a single webhook in a background thread (non-blocking).

    Prefer dispatch() for new code — it uses project webhook_config rules.
    """
    if not webhook_url:
        return
    payload = _build_payload(event, task, actor)
    thread  = threading.Thread(target=_post, args=(webhook_url, payload), daemon=True)
    thread.start()
