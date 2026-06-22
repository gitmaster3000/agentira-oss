
"""
Integration tests for Service Accounts (Bots) and Agent Identity.

Tests the "Service Account" model:
1. Humans: Cookie/Session based.
2. Bots: Created by Human -> API Key -> Agent uses Key.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend import services

# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_db():
    """Create an in-memory SQLite DB and patch SessionLocal for every test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession):
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession

# ── Tests ───────────────────────────────────────────────────────────────

def test_service_account_lifecycle():
    """Verify human creates bot, bot gets key, bot configures self."""
    
    # 1. Human creates Service Account (Bot)
    # Checks that creation returns the API key
    bot_profile = services.create_service_account("code_agent")
    assert bot_profile["name"] == "code_agent"
    assert bot_profile["account_type"] == "external_agent"
    assert "api_key" in bot_profile
    api_key = bot_profile["api_key"]
    
    # 2. Agent uses Key to Validate Identity (Simulates 'get_me')
    identified_bot = services.validate_api_key(api_key)
    assert identified_bot["id"] == bot_profile["id"]
    
    # 3. Agent configures itself (Simulates 'update_profile')
    # Agent sets a display name and avatar
    updated_bot = services.update_profile(
        identified_bot["id"], 
        display_name="Super Coder 9000", 
        avatar_url="http://avatar.com/bot.png"
    )
    assert updated_bot["display_name"] == "Super Coder 9000"
    assert updated_bot["avatar_url"] == "http://avatar.com/bot.png"

def test_api_key_security():
    """Verify keys are not leaked via standard get_profile."""
    # 1. Setup
    bot = services.create_service_account("secure_bot")
    
    # 2. Get Profile normally (should NOT show key)
    fetched = services.get_profile(bot["id"])
    assert "api_key" not in fetched
    
    # 3. Validate random key fails
    with pytest.raises(ValueError, match="Invalid API key"):
        services.validate_api_key("invalid-key-123")

def test_bot_permissions():
    """Verify bot permissions (same as member)."""
    # 1. Create Bot
    bot = services.create_service_account("worker_bot")
    bot_key = bot["api_key"]
    
    # 2. Create Project (as human admin)
    admin = services.create_profile("admin", role="admin")
    proj = services.create_project("Skynet", actor="admin")
    
    # 3. Add Bot to Project
    services.add_project_member(proj["id"], "worker_bot", actor="admin")
    
    # 4. Bot creates task
    task = services.create_task(proj["id"], "Build Core", actor="worker_bot")
    assert task["title"] == "Build Core"
    
    # 5. Activity log shows bot name
    activity = services.get_activity(task["id"])
    assert activity[0]["actor"] == "worker_bot"

