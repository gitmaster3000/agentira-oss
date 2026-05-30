"""AP-152 regression: `get_or_create_conductor` must NOT overwrite a
user-edited `system_prompt` on subsequent calls.

PR #92 introduced an "always-sync from code" behavior that clobbered
user edits in Agent Settings — that violates the prompts-are-config
contract (see CLAUDE.md → Architecture). This test pins the fixed
"set-if-empty" behavior so the regression can't sneak back in.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import Base
from backend import services as core_services
from backend.forge import conductor
from backend.models import Profile


@pytest.fixture(autouse=True)
def test_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with patch("backend.services.SessionLocal", TestSession), \
         patch("backend.forge.services.SessionLocal", TestSession), \
         patch("backend.forge.conductor.SessionLocal", TestSession):
        db = TestSession()
        core_services._seed_defaults(db)
        db.close()
        yield TestSession


def test_user_edited_conductor_prompt_is_preserved(test_db):
    # First call seeds the Conductor with the canonical system prompt.
    conductor.get_or_create_conductor()

    # User edits the prompt via Agent Settings (simulated direct write).
    USER_EDITED = "You are MY conductor. Be terse. Always brief first."
    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        assert prof is not None
        prof.system_prompt = USER_EDITED
        db.commit()

    # Subsequent calls (queue tick, kickoff seed, dispatch — any of them)
    # must NOT re-apply the code constant.
    conductor.get_or_create_conductor()
    conductor.get_or_create_conductor()

    with test_db() as db:
        prof = db.query(Profile).filter(Profile.name == "Conductor").first()
        assert prof.system_prompt == USER_EDITED, (
            "User-edited Conductor prompt was overwritten — "
            "prompts-are-config contract broken."
        )
