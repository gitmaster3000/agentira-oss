"""Data access for agent-to-agent threads and messages. Services compose;
repos own the SQL (CLAUDE.md). Functions take a session; callers commit."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from backend.forge.models import (
    A2AMessage, A2AThread, Agent, ForgeRuntime, Run, RunStatus,
)
from backend.models import Profile, ProjectMember, Project


def find_agent(db, ident: str) -> tuple[Agent, Profile] | None:
    """An agent by profile name, display name or id, with its profile. Archived
    agents are returned too (their profile has archived_at set)."""
    row = (db.query(Agent, Profile)
             .join(Profile, Agent.profile_id == Profile.id)
             .filter(or_(Profile.name == ident, Profile.display_name == ident,
                         Agent.id == ident))
             .order_by(Profile.archived_at.isnot(None), Agent.created_at)
             .first())
    return (row[0], row[1]) if row else None


def agent_for_profile_name(db, name: str) -> tuple[Agent, Profile] | None:
    row = (db.query(Agent, Profile)
             .join(Profile, Agent.profile_id == Profile.id)
             .filter(Profile.name == name).first())
    return (row[0], row[1]) if row else None


def create_thread(db, *, project_id: str | None, task_id: str | None,
                  subject: str, created_by_agent_id: str,
                  origin_run_id: str | None,
                  origin_scope_key: str | None) -> A2AThread:
    th = A2AThread(project_id=project_id, task_id=task_id, subject=subject,
                   created_by_agent_id=created_by_agent_id,
                   origin_run_id=origin_run_id,
                   origin_scope_key=origin_scope_key)
    db.add(th)
    db.flush()
    return th


def get_thread(db, thread_id: str) -> A2AThread | None:
    return db.get(A2AThread, thread_id)


def add_message(db, *, thread: A2AThread, from_agent_id: str, to_agent_id: str,
                kind: str, body: str) -> A2AMessage:
    msg = A2AMessage(thread_id=thread.id, from_agent_id=from_agent_id,
                     to_agent_id=to_agent_id, kind=kind, body=body)
    db.add(msg)
    db.flush()
    return msg


def thread_messages(db, thread_id: str) -> list[A2AMessage]:
    return (db.query(A2AMessage)
              .filter(A2AMessage.thread_id == thread_id)
              .order_by(A2AMessage.created_at, A2AMessage.id)
              .all())


def thread_participant_ids(db, thread: A2AThread) -> set[str]:
    ids = {thread.created_by_agent_id}
    for frm, to in (db.query(A2AMessage.from_agent_id, A2AMessage.to_agent_id)
                      .filter(A2AMessage.thread_id == thread.id)):
        ids.update((frm, to))
    return ids


def count_messages_since(db, thread_id: str, since: datetime) -> int:
    return (db.query(A2AMessage)
              .filter(A2AMessage.thread_id == thread_id,
                      A2AMessage.created_at >= since)
              .count())


def live_run_for_agent(db, agent_id: str) -> Run | None:
    """The agent's most recent RUNNING run, if any."""
    return (db.query(Run)
              .filter(Run.agent_id == agent_id, Run.status == RunStatus.RUNNING)
              .order_by(Run.created_at.desc())
              .first())


def run_is_running(db, run_id: str) -> bool:
    return (db.query(Run.id)
              .filter(Run.id == run_id, Run.status == RunStatus.RUNNING)
              .first()) is not None


def agent_cards_rows(db, *, project_id: str | None = None):
    """(Agent, Profile, ForgeRuntime|None) for every live managed agent, newest
    first; optionally only members of one project. Org scoping is the
    session's."""
    q = (db.query(Agent, Profile, ForgeRuntime)
           .join(Profile, Agent.profile_id == Profile.id)
           .outerjoin(ForgeRuntime, Agent.runtime_id == ForgeRuntime.id)
           .filter(Profile.archived_at.is_(None),
                   Agent.runtime_id.isnot(None)))
    if project_id:
        q = q.join(ProjectMember, ProjectMember.profile_id == Profile.id) \
             .filter(ProjectMember.project_id == project_id)
    return q.order_by(Agent.created_at).all()


def busy_agent_ids(db, agent_ids: list[str]) -> set[str]:
    if not agent_ids:
        return set()
    return {a for (a,) in db.query(Run.agent_id)
            .filter(Run.agent_id.in_(agent_ids), Run.status == RunStatus.RUNNING)
            .distinct()}


def projects_by_profile(db, profile_ids: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    if not profile_ids:
        return out
    rows = (db.query(ProjectMember.profile_id, Project.id, Project.name)
              .join(Project, Project.id == ProjectMember.project_id)
              .filter(ProjectMember.profile_id.in_(profile_ids))
              .order_by(Project.name))
    for pid, proj_id, name in rows:
        out.setdefault(pid, []).append({"id": proj_id, "name": name})
    return out
