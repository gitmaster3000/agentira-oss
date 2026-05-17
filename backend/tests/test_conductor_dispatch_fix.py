"""Regression tests for the handover blockers found during live bring-up:

1. create_agent must mint an api_key — without it the agent's `agentira`
   MCP server gets no Authorization header and the agent can't call
   finish_run / update_task / add_comment.
2. _dispatch_coro must marshal dispatch coroutines onto the main loop
   when called from a background thread (the AP-80 Conductor ticks in
   APScheduler's threadpool, which has no event loop).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import ForgeRuntime


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def test_create_agent_mints_api_key():
    """A managed agent's backing profile must get an api_key so the
    `agentira` MCP server can authenticate it."""
    with forge_services._session() as db:
        rt = ForgeRuntime(id=uuid.uuid4().hex[:12], daemon_id="d1",
                          provider="claude", binary_path="/bin/claude",
                          status="online")
        db.add(rt)
        db.commit()
        rt_id = rt.id

    result = forge_services.create_agent(name="demo-agent", runtime_id=rt_id)
    assert "error" not in result

    from backend.models import Profile
    with forge_services._session() as db:
        prof = db.query(Profile).filter(Profile.name == "demo-agent").first()
        assert prof is not None
        assert prof.api_key, "create_agent must mint an api_key"
        assert len(prof.api_key) >= 32


def test_dispatch_coro_runs_in_async_context():
    """In an async context the coroutine is attached to the running loop."""
    ran = {"v": False}

    async def _coro():
        ran["v"] = True

    async def _main():
        forge_services._dispatch_coro(_coro())
        await asyncio.sleep(0.05)  # let the created task run

    asyncio.run(_main())
    assert ran["v"] is True


def test_dispatch_coro_marshals_from_background_thread():
    """The Conductor calls _dispatch_coro from an APScheduler thread that
    has no event loop. It must marshal onto the captured main loop."""
    ran = threading.Event()

    async def _coro():
        ran.set()

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    try:
        forge_services.set_main_loop(loop)
        # Call from THIS thread — no running loop here, like the Conductor.
        forge_services._dispatch_coro(_coro())
        assert ran.wait(timeout=2.0), "coroutine never ran on the main loop"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        forge_services.set_main_loop(None)


def test_dispatch_coro_no_loop_does_not_raise():
    """With no main loop captured, a background-thread dispatch logs and
    drops rather than raising — one bad dispatch must not crash the tick."""
    forge_services.set_main_loop(None)

    async def _coro():
        pass

    # Must not raise.
    forge_services._dispatch_coro(_coro())
