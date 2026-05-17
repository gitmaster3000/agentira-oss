"""The Concierge — a system-provided guide agent.

Unlike worker agents, the Concierge does not run code or pick up tasks.
It is the always-available assistant behind the floating chat button:
it answers "how do I…" questions, explains what's on screen, and helps
the user navigate their projects, tasks, agents, and runs.

It is seeded once (`get_or_create_concierge`), marked `is_system` so it
cannot be deleted, and reachable workspace-wide.
"""

from __future__ import annotations

import logging
import secrets

from backend.db import SessionLocal
from backend.models import Profile, Role
from backend.forge.models import Agent, ForgeRuntime

logger = logging.getLogger("agentira.forge.concierge")

CONCIERGE_NAME = "Concierge"

# The Concierge runs on a small fast model — it is a guide, not a coder.
CONCIERGE_DEFAULT_MODEL = "claude-sonnet-4-5"

CONCIERGE_SYSTEM_PROMPT = """\
You are the Concierge — the built-in guide for this Agentira workspace.
You sit behind the floating chat button and help the user get things done.

What you do:
- Explain what's on the user's current screen and how Agentira works
  (projects, tasks, the board, agents, runs, the Conductor).
- Help the user navigate: where to create a task, how to assign an
  agent, how to start or review a run.
- Answer "how do I…" and "what does this mean" questions concisely.

Use the agentira MCP tools (get_me, list_projects, get_project, get_task,
list_tasks, list_agents, get_activity, …) to look things up before
answering — never guess at the user's actual data.

You do NOT write code, pick up tasks, or dispatch runs yourself. When the
user wants work done, guide them to assign it to a worker agent (or to
the Conductor for autonomous pickup). Be warm, brief, and concrete."""


def get_or_create_concierge() -> dict:
    """Return the Concierge agent, seeding it once if absent.

    Mirrors `conductor.get_or_create_conductor`: a real Agent row with a
    bound Claude runtime so the floating chat can take an LLM turn. Marked
    `is_system` so the UI protects it from deletion.
    """
    with SessionLocal() as db:
        prof = db.query(Profile).filter(Profile.name == CONCIERGE_NAME).first()
        if prof is None:
            role = db.query(Role).filter(Role.name == "bot").first()
            if role is None:
                return {"error": "bot role missing"}
            prof = Profile(
                name=CONCIERGE_NAME, display_name="Concierge",
                password_hash="", avatar_url="", webhook_url="",
                role_id=role.id, api_key=secrets.token_hex(32),
            )
            db.add(prof)
            db.commit()
            db.refresh(prof)
            logger.info("Seeded Concierge profile %s", prof.id)

        claude_rt = (db.query(ForgeRuntime)
                       .filter(ForgeRuntime.provider == "claude")
                       .first())
        rt_id = claude_rt.id if claude_rt else None

        if not prof.system_prompt:
            prof.system_prompt = CONCIERGE_SYSTEM_PROMPT
        if not prof.model:
            prof.model = CONCIERGE_DEFAULT_MODEL
        if rt_id and not prof.runtime_id:
            prof.runtime_id = rt_id
        prof.is_system = True

        agent = db.query(Agent).filter(Agent.id == prof.id).first()
        if agent is None:
            agent = Agent(
                id=prof.id, profile_id=prof.id, name=CONCIERGE_NAME,
                executor_type="http", model=prof.model, runtime_id=rt_id,
            )
            db.add(agent)
        elif rt_id and not agent.runtime_id:
            agent.runtime_id = rt_id
        db.commit()
        logger.info("Concierge agent ready: %s (runtime=%s)",
                    prof.id, "set" if rt_id else "none")
        return {"id": prof.id, "name": prof.name,
                "model": prof.model, "runtime_bound": bool(rt_id)}
