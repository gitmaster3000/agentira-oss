"""AP-152: project + task attachments.

Single focused module — functions, not class hierarchies. One `Attachment`
table backs both task-scoped and project-scoped files (row carries
`task_id` XOR `project_id`).

Storage layout under `data/attachments/`:
- task attachments: `<task_id>/<safe_name>` (preserves the pre-AP-152 path)
- project attachments: `projects/<project_id>/<safe_name>`

`backend.services` still exposes `add_attachment` / `list_attachments` /
`get_attachment` / `get_attachment_bytes` / `delete_attachment` as thin
shims that call this module, so existing REST + MCP callers keep working.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from backend.db import SessionLocal
from backend.models import Activity, Attachment, Project, Task


# Defaults to local disk under the repo. In prod (Railway) set
# AGENTIRA_ATTACHMENTS_DIR to a mounted persistent volume so files survive
# redeploys — the container filesystem is ephemeral. ponytail: local-disk only;
# object storage (S3/GCS) is the next step if multi-instance/scale lands.
ATTACHMENTS_DIR = os.getenv("AGENTIRA_ATTACHMENTS_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "attachments",
)

# Text MIME prefixes/types that `list_for_project` and `read_text` can
# inline without base64 encoding. Anything outside this set goes through
# the download URL + AGENTIRA_API_KEY route.
_TEXT_PREFIXES = ("text/",)
_TEXT_EXTRA = {
    "application/json", "application/xml", "application/yaml",
    "application/x-yaml", "application/toml", "application/x-toml",
    "application/javascript", "application/x-sh",
}


def _is_text(content_type: str) -> bool:
    if not content_type:
        return False
    if content_type.startswith(_TEXT_PREFIXES):
        return True
    return content_type.split(";", 1)[0].strip() in _TEXT_EXTRA


def _to_dict(a: Attachment) -> dict:
    return {
        "id": a.id,
        "task_id": a.task_id,
        "project_id": a.project_id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "uploaded_by": a.uploaded_by,
        "download_url": f"/api/attachments/{a.id}/download",
        "created_at": a.created_at.isoformat(),
    }


def _download_hint(download_url: str, filename: str) -> str:
    """Curl shape for fetching a binary attachment over HTTP. References the
    agent's $AGENTIRA_API_KEY env var (not its value) and leaves the API base
    as a placeholder — no hardcoded host, no leaked credentials."""
    return (
        "Binary file — download over HTTP with your agent key (already in env): "
        f'curl -H "Authorization: Bearer $AGENTIRA_API_KEY" '
        f'"<API_BASE_URL>{download_url}" -o "{filename}"'
    )


def _storage_dir(task_id: str | None, project_id: str | None) -> str:
    if task_id:
        return os.path.join(ATTACHMENTS_DIR, task_id)
    return os.path.join(ATTACHMENTS_DIR, "projects", project_id)


def add(
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    uploaded_by: str = "system",
) -> dict:
    """Persist an attachment scoped to exactly one of task_id or project_id."""
    if bool(task_id) == bool(project_id):
        raise ValueError("add() requires exactly one of task_id or project_id")

    with SessionLocal() as db:
        # Resolve+validate the owner row so callers can pass a task key
        # like 'AGNT-1' for tasks (same lenient lookup services.py used).
        if task_id:
            task = db.get(Task, task_id)
            if not task:
                task = db.query(Task).filter(Task.key == task_id.upper()).first()
            if not task:
                raise ValueError(f"Task {task_id} not found")
            task_id = task.id
        else:
            project = db.get(Project, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")
            project_id = project.id

        target_dir = _storage_dir(task_id, project_id)
        os.makedirs(target_dir, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        file_path = os.path.join(target_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        att = Attachment(
            task_id=task_id,
            project_id=project_id,
            filename=filename,
            content_type=content_type,
            file_path=file_path,
            size_bytes=len(file_bytes),
            uploaded_by=uploaded_by,
        )
        db.add(att)
        db.add(Activity(
            project_id=project_id,
            task_id=task_id,
            actor=uploaded_by,
            action="attached",
            detail=f"Attached: {filename}",
        ))
        db.commit()
        db.refresh(att)
        return _to_dict(att)


def list_for_task(task_id: str) -> list[dict]:
    with SessionLocal() as db:
        # Resolve a task key like 'AP-280' to its internal id, matching add().
        if not db.get(Task, task_id):
            t = db.query(Task).filter(Task.key == task_id.upper()).first()
            if t:
                task_id = t.id
        rows = (
            db.query(Attachment)
              .filter(Attachment.task_id == task_id)
              .order_by(Attachment.created_at.desc())
              .all()
        )
        return [_to_dict(a) for a in rows]


def list_for_project(project_id: str, *, inline_text_max: int = 50_000) -> list[dict]:
    """List project attachments. Text files under the byte budget get an
    `inline_text` field so MCP consumers don't have to round-trip for the
    most-common case (briefs, READMEs, specs)."""
    with SessionLocal() as db:
        rows = (
            db.query(Attachment)
              .filter(Attachment.project_id == project_id)
              .order_by(Attachment.created_at.desc())
              .all()
        )
        out: list[dict] = []
        for a in rows:
            d = _to_dict(a)
            if (
                _is_text(a.content_type)
                and a.size_bytes
                and a.size_bytes <= inline_text_max
                and os.path.exists(a.file_path)
            ):
                try:
                    with open(a.file_path, "r", encoding="utf-8") as fh:
                        d["inline_text"] = fh.read()
                except UnicodeDecodeError:
                    pass
            out.append(d)
        return out


def get(attachment_id: str) -> tuple[dict, str] | None:
    """Metadata + file path. Used by REST download route."""
    with SessionLocal() as db:
        a = db.get(Attachment, attachment_id)
        if not a:
            return None
        return _to_dict(a), a.file_path


def get_bytes(attachment_id: str) -> tuple[dict, bytes] | None:
    """Metadata + raw bytes. Used by the legacy base64 MCP download tool."""
    with SessionLocal() as db:
        a = db.get(Attachment, attachment_id)
        if not a or not os.path.exists(a.file_path):
            return None
        with open(a.file_path, "rb") as f:
            return _to_dict(a), f.read()


def read_text(attachment_id: str) -> dict[str, Any] | None:
    """MCP-friendly read.

    For text/* (under 200KB safety cap): returns the raw text inline.
    For everything else: returns the metadata + `download_url`; the caller
    downloads it over HTTP with its own credentials. No base64.
    """
    with SessionLocal() as db:
        a = db.get(Attachment, attachment_id)
        if not a:
            return None
        meta = _to_dict(a)
        if (
            _is_text(a.content_type)
            and a.size_bytes <= 200_000
            and os.path.exists(a.file_path)
        ):
            try:
                with open(a.file_path, "r", encoding="utf-8") as fh:
                    meta["content"] = fh.read()
                    return meta
            except UnicodeDecodeError:
                pass
        # Binary or oversized text: no inline content. Hint how to fetch it —
        # $AGENTIRA_API_KEY is an env reference the agent already has, so it
        # resolves at runtime without exposing the key value. No hardcoded host.
        meta["served_over_http"] = True
        meta["download_hint"] = _download_hint(meta["download_url"], a.filename)
        return meta


def delete(attachment_id: str) -> bool:
    with SessionLocal() as db:
        a = db.get(Attachment, attachment_id)
        if not a:
            return False
        if os.path.exists(a.file_path):
            try:
                os.remove(a.file_path)
            except OSError:
                pass
        db.delete(a)
        db.commit()
        return True
