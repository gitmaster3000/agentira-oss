"""AP-190: compaction when a task is completed.

When a task moves to *done*, every agent's (agent, task) conversation is
compacted so a later reopen (e.g. back to review) starts from a short summary
instead of replaying the whole prior conversation:

  1. The latest finished run's handoff summary is promoted to the
     conversation's carry-over summary (`rolling_summary`).
  2. The native resume handle (`runtime_session_id`) is dropped.

On the next dispatch `assemble_context` sees no native resume, so it rebuilds
the prompt from the summary + recent turns within the token budget — the long
transcript stays on disk/in the DB but is no longer dragged back in full.

Keying is by `scope_key = "task:<id>"`, which is per (agent, task) — so a
task's planner, implementer and reviewer conversations each compact
independently.
"""

from __future__ import annotations

import logging

from backend.forge.models import Conversation, Run
from backend.forge.services import _session

logger = logging.getLogger("agentira.forge.compaction")


def compact_task_on_done(task_id: str) -> int:
    """Compact every (agent, task) conversation for a completed task.

    Returns the number of conversations compacted. Idempotent — re-running on
    an already-compacted task just re-clears the (already empty) handle.
    """
    if not task_id:
        return 0
    scope = f"task:{task_id}"
    compacted = 0
    with _session() as db:
        convs = (db.query(Conversation)
                   .filter(Conversation.scope_key == scope)
                   .all())
        for conv in convs:
            if not conv.rolling_summary:
                latest = (db.query(Run)
                            .filter(Run.agent_id == conv.agent_id,
                                    Run.task_id == task_id,
                                    Run.summary.isnot(None))
                            .order_by(Run.finished_at.desc().nullslast(),
                                      Run.created_at.desc())
                            .first())
                if latest and latest.summary:
                    conv.rolling_summary = latest.summary.strip() or None
                    conv.rolling_summary_through_run_id = latest.id
            # Drop the native resume handle so reopen rebuilds from the summary
            # + bounded history rather than replaying the whole session.
            conv.runtime_session_id = None
            compacted += 1
        if compacted:
            db.commit()
    if compacted:
        logger.info("Compacted %d conversation(s) for done task %s",
                    compacted, task_id)
    return compacted
