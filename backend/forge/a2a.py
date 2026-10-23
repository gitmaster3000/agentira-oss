"""Agent-to-agent messaging inside Agentira (A2A, visible on the board).

An agent asks a colleague with `ask`; the colleague is woken in its own
`a2a:<thread_id>` conversation (queued behind a running turn by the existing
msg_queue) and answers with `ask` on the same thread. A reply goes back into
the asker's live run conversation when it still has one, else wakes the asker
in the a2a conversation. Functions raise A2AError with a plain-language
message; the MCP layer turns it into `{"error": ...}`.

SQL lives in backend/forge/repos/a2a.py. Docs: docs-oss/docs/technical/a2a.md.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.auth import require_project_access
from backend.db import SessionLocal
from backend.forge.repos import a2a as repo
from backend.forge.repos import activities as activities_repo
from backend.forge.repos import tasks as tasks_repo

logger = logging.getLogger("agentira.forge.a2a")

MAX_BODY_CHARS = 8000
MAX_MESSAGES_PER_THREAD_PER_HOUR = 30
_SNIPPET_CHARS = 200


class A2AError(ValueError):
    """A refusal the calling agent can read and act on."""


def _snippet(text: str) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= _SNIPPET_CHARS else one_line[:_SNIPPET_CHARS - 1] + "…"


def _clean_body(message: str) -> str:
    body = (message or "").strip()
    if not body:
        raise A2AError("The message is empty.")
    if len(body) > MAX_BODY_CHARS:
        raise A2AError(f"The message is too long ({len(body)} characters; "
                       f"the limit is {MAX_BODY_CHARS}). Shorten it.")
    return body


def _caller(db, actor: str):
    row = repo.agent_for_profile_name(db, actor)
    if not row:
        raise A2AError("Only agents can use agent messaging.")
    return row


def _target(db, caller_profile, ident: str):
    """Resolve the agent being addressed: same org, exists, not archived, not
    the caller. Unknown and other-org agents read the same on purpose."""
    row = repo.find_agent(db, (ident or "").strip())
    if not row or row[1].org_id != caller_profile.org_id:
        raise A2AError(f"No agent named '{ident}'. Use list_agents to see who is available.")
    agent, prof = row
    if prof.archived_at is not None:
        raise A2AError(f"Agent '{ident}' has been archived and cannot be reached.")
    if prof.id == caller_profile.id:
        raise A2AError("You cannot message yourself.")
    return agent, prof


def _task_line(task) -> str:
    return f" · task {task.key or task.id}: {task.title}" if task else ""


def _wire_text(sender: str, thread_id: str, task, body: str) -> str:
    """What the receiving agent reads: who wrote, which thread and task, the
    message, and exactly how to answer."""
    return (
        f"[Message from agent {sender}] thread {thread_id}{_task_line(task)}\n\n"
        f"{body}\n\n"
        f'To answer, call ask_agent(agent="{sender}", thread_id="{thread_id}", '
        f'message="..."). {sender} only sees what you send that way.'
    )


def _deliver(*, agent_id: str, text: str, scope_key: str) -> bool:
    # Lazy import: forge services import a lot, and tests patch the attribute.
    from backend.forge import services as forge_services
    try:
        res = forge_services.send_runtime_message(
            agent_id, content=text, scope_key=scope_key)
    except Exception as exc:  # noqa: BLE001 — the message is stored regardless
        logger.warning("a2a delivery failed agent=%s: %s", agent_id, exc)
        return False
    return isinstance(res, dict) and not res.get("error") and res.get("success") is not False


def ask(actor: str, agent: str, message: str, *, task_id: str | None = None,
        thread_id: str | None = None) -> dict:
    """Store a message and wake the target. New thread unless `thread_id`."""
    body = _clean_body(message)
    with SessionLocal() as db:
        me, me_prof = _caller(db, actor)
        target, target_prof = _target(db, me_prof, agent)

        task = None
        if thread_id:
            th = repo.get_thread(db, thread_id)
            if not th or me.id not in repo.thread_participant_ids(db, th):
                raise A2AError(f"Thread '{thread_id}' not found.")
            kind = "ask" if me.id == th.created_by_agent_id else "reply"
            if th.task_id:
                task = tasks_repo.resolve_ref(db, th.task_id)
            hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            if repo.count_messages_since(db, th.id, hour_ago) >= MAX_MESSAGES_PER_THREAD_PER_HOUR:
                raise A2AError(
                    f"This thread already has {MAX_MESSAGES_PER_THREAD_PER_HOUR} "
                    "messages in the last hour. Wait before sending more.")
        else:
            if task_id:
                task = tasks_repo.resolve_ref(db, task_id)
                if not task:
                    raise A2AError(f"Task '{task_id}' not found.")
                try:
                    require_project_access(db, actor, task.project_id, "read")
                except PermissionError:
                    raise A2AError(f"Task '{task_id}' not found.") from None
            live = repo.live_run_for_agent(db, me.id)
            th = repo.create_thread(
                db, project_id=task.project_id if task else None,
                task_id=task.id if task else None,
                subject=_snippet(body)[:120], created_by_agent_id=me.id,
                origin_run_id=live.id if live else None,
                origin_scope_key=(f"task:{live.task_id}"
                                  if live and live.task_id else None))
            kind = "ask"

        msg = repo.add_message(db, thread=th, from_agent_id=me.id,
                               to_agent_id=target.id, kind=kind, body=body)
        if task:
            verb = "asked" if kind == "ask" else "replied to"
            activities_repo.add_task_comment(
                db, project_id=task.project_id, task_id=task.id, actor=me_prof.name,
                detail=f"{me_prof.name} {verb} {target_prof.name}: {_snippet(body)}")

        # Back into the asker's live run conversation when it still has one.
        scope = f"a2a:{th.id}"
        if (target.id == th.created_by_agent_id and th.origin_run_id
                and th.origin_scope_key and repo.run_is_running(db, th.origin_run_id)):
            scope = th.origin_scope_key
        text = _wire_text(me_prof.name, th.id, task, body)
        out = {"thread_id": th.id, "message_id": msg.id}
        target_id, target_name = target.id, target_prof.name
        db.commit()

    out["delivered"] = _deliver(agent_id=target_id, text=text, scope_key=scope)
    if not out["delivered"]:
        out["note"] = (f"Saved, but {target_name} could not be woken right now "
                       "(no connected computer?). It will see the thread when it next works.")
    return out


def get_thread(actor: str, thread_id: str) -> dict:
    with SessionLocal() as db:
        me, _ = _caller(db, actor)
        th = repo.get_thread(db, thread_id)
        if not th or me.id not in repo.thread_participant_ids(db, th):
            raise A2AError(f"Thread '{thread_id}' not found.")
        msgs = repo.thread_messages(db, th.id)
        names = {a.id: p.name for a, p in
                 (repo.find_agent(db, i) for i in
                  {th.created_by_agent_id, *(m.from_agent_id for m in msgs),
                   *(m.to_agent_id for m in msgs)}) if a}
        return {
            "thread_id": th.id, "subject": th.subject, "task_id": th.task_id,
            "messages": [{
                "id": m.id, "from": names.get(m.from_agent_id, m.from_agent_id),
                "to": names.get(m.to_agent_id, m.to_agent_id), "kind": m.kind,
                "body": m.body, "created_at": m.created_at.isoformat(),
            } for m in msgs],
        }


def hand_off_task(actor: str, task_id: str, agent: str, note: str) -> dict:
    """Reassign a task to `agent`, leave the note on the task feed and start a
    run for it the way the Conductor does."""
    body = _clean_body(note)
    from backend import services as core_services
    from backend.forge import services as forge_services
    with SessionLocal() as db:
        row = repo.agent_for_profile_name(db, actor)
        actor_prof = row[1] if row else None
        task = tasks_repo.resolve_ref(db, task_id)
        if not task:
            raise A2AError(f"Task '{task_id}' not found.")
        try:
            require_project_access(db, actor, task.project_id, "write")
        except PermissionError:
            raise A2AError(f"Task '{task_id}' not found.") from None
        if actor_prof is None:
            actor_prof = repo.profile_by_name(db, actor)
        if actor_prof is None:
            raise A2AError("Unknown caller.")
        target, target_prof = _target(db, actor_prof, agent)
        task_pk, project_id = task.id, task.project_id
        target_id, target_name = target.id, target_prof.name

        thread_id = None
        if row:  # an agent handing off: keep the exchange readable as a thread
            th = repo.create_thread(
                db, project_id=project_id, task_id=task_pk,
                subject=_snippet(body)[:120], created_by_agent_id=row[0].id,
                origin_run_id=None, origin_scope_key=None)
            repo.add_message(db, thread=th, from_agent_id=row[0].id,
                             to_agent_id=target_id, kind="handoff", body=body)
            thread_id = th.id
        activities_repo.add_task_comment(
            db, project_id=project_id, task_id=task_pk, actor=actor,
            detail=f"{actor} handed this task to {target_name}: {body}")
        db.commit()

    core_services.update_task(task_pk, assignee=target_name, actor=actor)
    res = forge_services.schedule_task_run(
        task_id=task_pk, agent_id=target_id,
        extra_context=f"[Handed off by {actor}] {body}")
    if isinstance(res, dict) and res.get("error"):
        raise A2AError(f"Task reassigned to {target_name}, but its run could not start: "
                       f"{res['error']}")
    out = {"task_id": task_pk, "assignee": target_name,
           "run_id": (res or {}).get("run_id") or (res or {}).get("id")}
    if thread_id:
        out["thread_id"] = thread_id
    return out


def _first_line(text: str | None) -> str:
    return next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")[:200]


def list_agents(actor: str, project_id: str | None = None) -> list[dict]:
    """Agent cards (A2A AgentCard-like) for the caller's org."""
    from backend.forge import conductor
    from backend.forge import services as forge_services
    with SessionLocal() as db:
        if project_id:
            try:
                require_project_access(db, actor, project_id, "read")
            except PermissionError:
                raise A2AError(f"Project '{project_id}' not found.") from None
        rows = repo.agent_cards_rows(db, project_id=project_id)
        busy = repo.busy_agent_ids(db, [a.id for a, _, _ in rows])
        projects = repo.projects_by_profile(db, [p.id for _, p, _ in rows])
        cards = []
        for agent, prof, rt in rows:
            specialty = conductor._agent_specialty(prof)
            cards.append({
                "id": agent.id, "name": prof.name,
                "description": _first_line(prof.system_prompt) or specialty,
                "skills": [specialty] if specialty else [],
                "runtime": rt.provider if rt else None,
                "model": prof.model or agent.model or "",
                "online": forge_services._is_runtime_online(rt),
                "busy": agent.id in busy,
                "projects": projects.get(prof.id, []),
            })
        return cards
