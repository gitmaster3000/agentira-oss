"""Realistic, deterministic sample dataset for staging and PR previews (AP-699).

`seed()` builds one self-contained "preview" org: 4 projects of different sizes,
long markdown tasks, activity, comments, commits, PR links, attachments, past
runs (terminal states only) and notifications. Everything is written straight
to the DB — no services that wake agents, no daemon, no network, no LLM.

Idempotent: if the preview org exists, `seed()` is a no-op. `seed(reset=True)`
drops and rebuilds only that org (see `reset.delete_org`).
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timedelta, timezone

from backend import attachments, passwords
from backend.db import SessionLocal, privileged
from backend.forge.models import (
    Agent, AgentMessage, MessageRole, Run, RunOutcome, RunStatus,
)
from backend.models import (
    Activity, Attachment, Epic, Milestone, Notification, Org, Profile, Project,
    ProjectMember, Role, Status, Task, TaskCommit, TaskDependency, TaskPriority,
)
from backend.sample_data import content
from backend.sample_data.reset import delete_org

PREVIEW_USER = "preview"
PREVIEW_PASSWORD = "preview1234"
SEED = 699
_REPO = "https://github.com/agentira-preview/sample-app"
_HUMANS = [("alex", "Alex Rivera"), ("sam", "Sam Okafor"), ("jordan", "Jordan Lee")]
_STATUS_WEIGHTS = {  # name -> weight
    "big": [("done", 52), ("backlog", 18), ("todo", 12), ("in_progress", 9), ("review", 9)],
    "mid": [("done", 30), ("backlog", 20), ("todo", 20), ("in_progress", 15), ("review", 15)],
}
_PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082")
# name, key prefix, tasks, epics, milestones, weights, rich (DoD on every task)
_PROJECTS = [
    ("Agentira Platform", "AP", 600, 14, 6, "big", False),
    ("Mobile App", "MOB", 120, 6, 3, "mid", False),
    ("Easy ESG", "ESG", 60, 8, 4, "mid", True),
    ("Fresh Start", "NEW", 4, 0, 0, "mid", False),
]


def _id(label: str) -> str:
    return hashlib.sha1(f"ap699:{label}".encode()).hexdigest()[:12]


PREVIEW_ORG_ID = _id("org")


def _sha(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()


def _pick(rng, weighted):
    return rng.choices([n for n, _ in weighted], [w for _, w in weighted])[0]


def seed(reset: bool = False, now: datetime | None = None) -> dict:
    """Seed the preview org. Returns `{"created": bool}`."""
    now = now or datetime.now(timezone.utc)
    with privileged(), SessionLocal() as db:
        from backend import services
        services._seed_defaults(db)  # roles/statuses on a never-bootstrapped DB
        db.commit()
        exists = db.get(Org, PREVIEW_ORG_ID) is not None
        if exists and not reset:
            return {"created": False}
        if exists:
            delete_org(db, PREVIEW_ORG_ID)
        db.add(Org(id=PREVIEW_ORG_ID, name="Preview Org", max_members=50, max_agents=50))
        db.commit()

    services.seed_org_defaults(PREVIEW_ORG_ID)  # default agent team, no runtimes

    rng = random.Random(SEED)
    with privileged(), SessionLocal() as db:
        people = _people(db)
        agents = _agent_rows(db, now)
        statuses = {s.name: s.id for s in db.query(Status).all()}
        notif_pool: list[tuple[Task, Project]] = []
        for spec in _PROJECTS:
            _project(db, rng, now, spec, people, agents, statuses, notif_pool)
        _notifications(db, rng, now, people[0], notif_pool)
        db.commit()
    return {"created": True}


def _people(db) -> list[Profile]:
    role = {r.name: r for r in db.query(Role).all()}
    pw = passwords.hash_password(PREVIEW_PASSWORD)
    people = []
    for name, display, roles in ([(PREVIEW_USER, "Preview User", ["admin"])]
                                 + [(n, d, ["member"]) for n, d in _HUMANS]):
        p = Profile(
            id=_id(f"profile:{name}"), org_id=PREVIEW_ORG_ID, name=name, display_name=display,
            email=f"{name}@preview.agentira.dev", account_type="human",
            roles=[role[r] for r in roles], password_hash=pw,
            must_change_password=False,
            api_key=hashlib.sha256(f"ap699-{name}".encode()).hexdigest())
        db.add(p)
        people.append(p)
    db.commit()
    return people


def _agent_rows(db, now) -> list[Agent]:
    """forge_agents rows (needed by runs) for the seeded agent profiles."""
    rows = []
    for p in db.query(Profile).filter(Profile.org_id == PREVIEW_ORG_ID,
                                      Profile.account_type == "agentira_agent").all():
        a = Agent(id=_id(f"agent:{p.name}"), org_id=PREVIEW_ORG_ID, profile_id=p.id,
                  name=p.name, executor_type="http", model="sample", created_at=now)
        db.add(a)
        rows.append(a)
    db.commit()
    return rows


def _project(db, rng, now, spec, people, agents, statuses, notif_pool) -> None:
    name, prefix, n_tasks, n_epics, n_miles, weights, rich = spec
    pid = _id(f"project:{prefix}")
    span = {"AP": 150, "MOB": 90, "ESG": 60, "NEW": 2}[prefix]
    start = now - timedelta(days=span)
    proj = Project(id=pid, org_id=PREVIEW_ORG_ID, name=name, key_prefix=prefix,
                   description=content.paragraph(rng, 3), next_task_number=n_tasks + 1,
                   created_at=start)
    db.add(proj)
    for p in people:
        db.add(ProjectMember(id=_id(f"pm:{prefix}:{p.name}"), org_id=PREVIEW_ORG_ID,
                             project_id=pid, profile_id=p.id))
    db.flush()
    humans = [p.name for p in people]
    agent_names = [a.name for a in agents]
    colors = ["#7c4dff", "#26a69a", "#ef5350", "#ffa726", "#42a5f5", "#8d6e63"]

    epics = [Epic(id=_id(f"epic:{prefix}:{i}"), org_id=PREVIEW_ORG_ID, project_id=pid,
                  title=content.title(rng), description=content.paragraph(rng),
                  status=rng.choice(["backlog", "in_progress", "done"]), creator=PREVIEW_USER,
                  assignee=rng.choice(humans), color=colors[i % len(colors)],
                  created_at=start + timedelta(days=i)) for i in range(n_epics)]
    miles = [Milestone(id=_id(f"mile:{prefix}:{i}"), org_id=PREVIEW_ORG_ID, project_id=pid,
                       title=f"Release {i + 1}.0", description=content.paragraph(rng, 2),
                       due_date=start + timedelta(days=(i + 1) * span // (n_miles + 1)),
                       status="achieved" if i < n_miles // 2 else "planned",
                       creator=PREVIEW_USER, created_at=start) for i in range(n_miles)]
    db.add_all(epics + miles)
    db.flush()

    tasks: list[Task] = []
    for i in range(n_tasks):
        created = start + timedelta(seconds=(now - start).total_seconds() * i / n_tasks * 0.97)
        st = _pick(rng, _STATUS_WEIGHTS[weights])
        assignee = rng.choice(humans + agent_names + [""] * 3) if st != "backlog" else ""
        r = rng.random()
        desc = (content.long_markdown(rng, content.title(rng), rng.randint(2000, 7500))
                if r < 0.35 or (rich and r < 0.7)
                else content.paragraph(rng) if r < 0.8 else "")
        done = st == "done"
        t = Task(
            id=_id(f"task:{prefix}:{i + 1}"), org_id=PREVIEW_ORG_ID, key=f"{prefix}-{i + 1}",
            type="bug" if rng.random() < 0.15 else "task", project_id=pid,
            epic_id=rng.choice(epics).id if epics and rng.random() < 0.8 else None,
            milestone_id=rng.choice(miles).id if miles and rng.random() < 0.4 else None,
            parent_id=(rng.choice(tasks).id if tasks and rng.random() < 0.08 else None),
            title=content.title(rng), description=desc, status_id=statuses[st],
            priority=rng.choices(list(TaskPriority), [2, 5, 3, 1])[0], assignee=assignee,
            creator=rng.choice(humans), created_at=created, updated_at=created,
            tags=",".join(rng.sample(content.TAGS, rng.randint(0, 3))),
            dod_items=(json.dumps(content.dod_items(rng, done))
                       if rich or rng.random() < 0.4 else None),
            start_date=created if st != "backlog" else None,
            due_date=created + timedelta(days=rng.randint(-5, 30)) if rng.random() < 0.4 else None,
            completed_at=created + timedelta(days=rng.randint(1, 10)) if done else None)
        tasks.append(t)
    db.add_all(tasks)
    db.flush()

    _links(db, rng, prefix, pid, tasks)
    _activity(db, rng, now, pid, tasks, humans, agent_names)
    _git(db, rng, prefix, tasks)
    _attachments(db, rng, tasks, n_tasks)
    _runs(db, rng, now, pid, tasks, agents)
    notif_pool.extend((t, proj) for t in tasks[-40:])
    db.flush()


def _links(db, rng, prefix, pid, tasks) -> None:
    seen = set()
    for i, t in enumerate(tasks[1:], 1):
        if rng.random() < 0.1:
            dep = tasks[rng.randrange(i)]  # earlier task only → stays acyclic
            if (t.id, dep.id) not in seen:
                seen.add((t.id, dep.id))
                db.add(TaskDependency(
                    id=_id(f"dep:{t.key}:{dep.key}"), org_id=PREVIEW_ORG_ID, project_id=pid,
                    task_id=t.id, depends_on_id=dep.id, creator=PREVIEW_USER,
                    created_at=t.created_at))


_PATH = ["backlog", "todo", "in_progress", "review", "done"]


def _activity(db, rng, now, pid, tasks, humans, agent_names) -> None:
    rows = []
    status_name = {}
    for st in db.query(Status).all():
        status_name[st.id] = st.name
    for t in tasks:
        base = t.created_at
        k = f"act:{t.key}"
        rows.append(Activity(
            id=_id(f"{k}:c"), org_id=PREVIEW_ORG_ID, project_id=pid, task_id=t.id,
            actor=t.creator, action="task.create", detail=f"Created task: {t.title}",
            created_at=base))
        cur = _PATH.index(status_name[t.status_id])
        for step in range(1, cur + 1):
            ts = base + timedelta(hours=step * rng.randint(2, 40))
            frm, to = _PATH[step - 1], _PATH[step]
            rows.append(Activity(
                id=_id(f"{k}:m{step}"), org_id=PREVIEW_ORG_ID, project_id=pid, task_id=t.id,
                actor=t.assignee or t.creator, action="task.move", detail=f"{frm} → {to}",
                diff=json.dumps({"status": {"from": frm, "to": to}}), created_at=ts))
        for c in range(rng.choice([0, 0, 1, 2, 3, 6])):
            mention = rng.choice(humans + agent_names)
            rows.append(Activity(
                id=_id(f"{k}:n{c}"), org_id=PREVIEW_ORG_ID, project_id=pid, task_id=t.id,
                actor=rng.choice(humans + agent_names), action="commented",
                detail=content.comment(rng, mention),
                created_at=base + timedelta(hours=rng.randint(1, 200))))
    db.add_all(rows)


def _git(db, rng, prefix, tasks) -> None:
    for t in tasks:
        if t.start_date is None or rng.random() > 0.35:
            continue
        slug = f"{t.key.lower()}-{t.title.lower().replace(' ', '-')[:30]}"
        t.branch = f"agent/task/{slug}"
        when = t.start_date or t.created_at
        for c in range(rng.randint(1, 3)):
            sha = _sha(f"{t.key}:{c}")
            db.add(TaskCommit(
                id=_id(f"commit:{t.key}:{c}"), org_id=PREVIEW_ORG_ID, task_id=t.id, sha=sha,
                message=f"{t.key}: {content.title(rng)}", author=t.assignee or t.creator,
                branch=t.branch, url=f"{_REPO}/commit/{sha}", repo="agentira-preview/sample-app",
                kind="commit", committed_at=when + timedelta(hours=c + 1), created_at=when))
        if t.completed_at is not None or rng.random() < 0.5:
            num = 100 + len(t.key) * 7 + int(t.key.split("-")[1])
            t.pr_url = f"{_REPO}/pull/{num}"
            db.add(TaskCommit(
                id=_id(f"pr:{t.key}"), org_id=PREVIEW_ORG_ID, task_id=t.id, sha=_sha(f"pr:{t.key}"),
                message=f"{t.key}: {t.title}", author=t.assignee or t.creator, branch=t.branch,
                url=t.pr_url, repo="agentira-preview/sample-app", kind="pr", pr_number=num,
                pr_state="merged" if t.completed_at else "open", committed_at=when,
                created_at=when))


def _attachments(db, rng, tasks, n_tasks) -> None:
    for t in rng.sample(tasks, min(len(tasks), max(1, n_tasks // 12))):
        for fname, ctype, kind, data in rng.choice([
            [("test-report.md", "text/markdown", "test-report",
              f"# Test report for {t.key}\n\n- 48 passed\n- 0 failed\n".encode())],
            [("screenshot.png", "image/png", "screenshot", _PNG_1X1)],
        ]):
            d = os.path.join(attachments.ATTACHMENTS_DIR, t.id)
            os.makedirs(d, exist_ok=True)
            path = os.path.join(d, fname)
            with open(path, "wb") as f:
                f.write(data)
            db.add(Attachment(
                id=_id(f"att:{t.key}:{fname}"), org_id=PREVIEW_ORG_ID, task_id=t.id,
                filename=fname, kind=kind, content_type=ctype, file_path=path,
                size_bytes=len(data), uploaded_by=t.assignee or t.creator,
                created_at=t.created_at + timedelta(hours=3)))


_TOOLS = [("Read", "src/app.py"), ("Edit", "src/app.py"), ("Bash", "pytest -q"),
          ("Bash", "git diff --stat"), ("Grep", "def handle")]


def _runs(db, rng, now, pid, tasks, agents) -> None:
    if not agents:
        return
    for t in tasks:
        if t.completed_at is None or rng.random() > 0.12:
            continue
        agent = rng.choice(agents)
        rid = _id(f"run:{t.key}")
        start = t.completed_at - timedelta(minutes=rng.randint(5, 90))
        fail = rng.random() < 0.15
        dur = rng.randint(40, 1500)
        db.add(Run(
            id=rid, agent_id=agent.id, task_id=t.id, project_id=pid, trigger_event="task.assigned",
            status=RunStatus.FAILED if fail else RunStatus.COMPLETED, model_used="sample-model",
            started_at=start, finished_at=start + timedelta(seconds=dur), duration_ms=dur * 1000,
            input_tokens=rng.randint(20_000, 400_000), output_tokens=rng.randint(2_000, 40_000),
            cost_usd=round(rng.uniform(0.05, 3.5), 2), is_work=True,
            outcome=RunOutcome.FAILED if fail else RunOutcome.SUCCEEDED,
            error="Sample failure: tests did not pass." if fail else None,
            summary=f"{content.paragraph(rng, 2)}",
            diff_stat=" 3 files changed, 84 insertions(+), 12 deletions(-)",
            artifacts_json=json.dumps([{"url": t.pr_url or _REPO, "label": "Pull request", "kind": "pr"}]),
            created_at=start))
        db.flush()
        for e in range(rng.randint(4, 10)):
            tool, arg = rng.choice(_TOOLS)
            db.add(AgentMessage(
                id=_id(f"msg:{t.key}:{e}"), agent_id=agent.id, run_id=rid, scope_key=f"run:{rid}",
                kind="run_step", role=MessageRole.ASSISTANT if e % 3 else MessageRole.TOOL,
                content=content.sentence(rng), tool_name=tool, tool_input=arg,
                created_at=start + timedelta(seconds=e * 20)))
        agent.total_runs = (agent.total_runs or 0) + 1


def _notifications(db, rng, now, user, pool) -> None:
    kinds = [("task.assigned", "was assigned to you"), ("commented", "has a new comment"),
             ("task.move", "moved to review")]
    for i, (t, proj) in enumerate(rng.sample(pool, min(24, len(pool)))):
        typ, text = kinds[i % len(kinds)]
        db.add(Notification(
            id=_id(f"notif:{i}"), org_id=PREVIEW_ORG_ID, profile_id=user.id, type=typ,
            title=f"{t.key} {text}", link=f"/tasks/{t.id}", read=i % 3 == 0,
            created_at=now - timedelta(hours=i * 5),
            meta=json.dumps({"task_key": t.key, "task_title": t.title, "project": proj.name})))
