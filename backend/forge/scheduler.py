"""Cron scheduler — fires agent runs based on forge_agents.schedule_* fields.

Uses APScheduler with a BackgroundScheduler. Reads enabled agents on startup
and whenever the /refresh endpoint is called.

Lifecycle: call start() in app lifespan, stop() on shutdown.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.db import SessionLocal
from backend.forge.models import Agent, ForgeRuntime, Run, RunStatus

logger = logging.getLogger("agentira.forge.scheduler")

_DAYS_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


class ForgeScheduler:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self) -> None:
        self._scheduler.start()
        self._load_jobs()
        logger.info("Forge scheduler started.")

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("Forge scheduler stopped.")

    def refresh(self) -> dict:
        """Re-read all agent schedules and rebuild jobs. Call after agent update."""
        self._scheduler.remove_all_jobs()
        count = self._load_jobs()
        return {"scheduled": count}

    # ── Internal ─────────────────────────────────────────────────────────

    def _load_jobs(self) -> int:
        count = 0
        with SessionLocal() as db:
            agents = db.query(Agent).filter(Agent.schedule_enabled == True).all()  # noqa: E712
            for a in agents:
                if not a.schedule_cron:
                    continue
                try:
                    trigger = CronTrigger.from_crontab(a.schedule_cron, timezone=a.schedule_tz or "UTC")
                    self._scheduler.add_job(
                        _fire_run,
                        trigger=trigger,
                        id=f"agent_{a.id}",
                        replace_existing=True,
                        kwargs={"agent_id": a.id},
                    )
                    count += 1
                    logger.debug("Scheduled agent %s (%s) cron=%s", a.name, a.id, a.schedule_cron)
                except Exception as exc:
                    logger.warning("Bad cron for agent %s: %s", a.id, exc)
        return count


def _fire_run(agent_id: str) -> None:
    """Create a forge Run for a scheduled agent and dispatch via WS."""
    with SessionLocal() as db:
        agent = db.get(Agent, agent_id)
        if not agent:
            return
        run = Run(
            agent_id=agent_id,
            trigger_event="scheduled",
            status=RunStatus.PENDING,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        runtime_id = agent.runtime_id

    logger.info("Scheduled run created: run=%s agent=%s", run_id, agent_id)

    if runtime_id:
        try:
            from backend.forge.ws_dispatch import hub
            import asyncio
            import uuid
            coro = hub.dispatch_task(
                runtime_id=runtime_id,
                task_id=run_id,  # use run_id as task identifier for scheduled runs
                agent_id=agent_id,
            )
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                asyncio.run(coro)
        except Exception as exc:
            logger.warning("WS dispatch for scheduled run failed: %s", exc)


# Singleton
scheduler = ForgeScheduler()
