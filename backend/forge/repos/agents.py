"""Data access for archiving an agent. Services compose; repos own the SQL."""
from __future__ import annotations

from datetime import datetime, timezone

from backend.models import ProjectMember


def archive_agent_rows(db, agent, profile) -> None:
    """Archive instead of delete: runs, chats and messages stay. The agent
    and its profile go inert (no runtime, no API key, no project access) and
    the profile name is freed for reuse. Caller commits."""
    stamp = datetime.now(timezone.utc)
    agent.runtime_id = None
    if profile is None:
        return
    original = profile.display_name or profile.name
    profile.archived_at = stamp
    profile.api_key = None
    profile.runtime_id = None
    profile.conductor_enabled = False
    profile.webhook_url = ""
    profile.name = f"{profile.name[:40]}-archived-{profile.id[:6]}"
    profile.display_name = f"{original} (archived)"
    agent.name = profile.display_name
    db.query(ProjectMember).filter(
        ProjectMember.profile_id == profile.id).delete(synchronize_session=False)
