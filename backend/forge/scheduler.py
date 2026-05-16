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
from apscheduler.triggers.interval import IntervalTrigger

from backend.db import SessionLocal
from backend.forge import conductor as _conductor
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
        # AP-80: Conductor tick — runs every TICK_INTERVAL_S to pick up
        # todo tasks for conductor-enabled agents.
        self._scheduler.add_job(
            _conductor.run_tick,
            trigger=IntervalTrigger(seconds=_conductor.TICK_INTERVAL_S),
            id="conductor_tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Forge scheduler started (conductor tick: %ss).",
                    _conductor.TICK_INTERVAL_S)

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
    """Create a forge Run for a scheduled agent and dispatch via the trigger rail.

    The agent prompt for scheduled runs is a placeholder today; templates +
    gate-driven work selection (planned) will populate the real prompt.
    """
    with SessionLocal() as db:
        agent = db.get(Agent, agent_id)
        if not agent or not agent.runtime_id:
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

    logger.info("Scheduled run created: run=%s agent=%s", run_id, agent_id)

    # TODO: source a real prompt (from agent system_prompt + template task selector)
    placeholder = "Scheduled run — no prompt source wired yet."
    try:
        from backend.forge import services
        services.dispatch_trigger(agent_id, placeholder, run_id=run_id, kind="run_step")
    except Exception as exc:
        logger.warning("dispatch_trigger for scheduled run failed: %s", exc)


# Singleton
scheduler = ForgeScheduler()
