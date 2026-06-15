"""Shared test fixtures.

Multi-tenancy (#115) made `org_id` NOT NULL and stamps it from the current-org
ContextVar via a `before_flush` listener registered on the app `SessionLocal`
(`backend.db`). The test suite swaps in its OWN sessionmaker (patching
`backend.services.SessionLocal`), which never carried that listener — so every
org-scoped insert went in with `org_id=NULL` and failed
`NOT NULL constraint failed: projects.org_id` (165 tests).

Fix is test-only:
  1. Register the same org-stamping listener on the base `Session` class, so the
     tests' plain sessionmaker gets stamping too (prod is untouched — this only
     runs when conftest is imported, i.e. under pytest).
  2. Run every test under the stable system org id.
  3. Import the full model set so `Base.metadata.create_all()` in the per-file
     fixtures builds the whole schema (incl. forge_* FK targets) regardless of
     which subset of files runs.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import backend.models  # noqa: F401  — register full schema
import backend.forge.models  # noqa: F401
from backend.db import get_current_org, set_current_org

# Stable id from services._ensure_system_org (VARCHAR(12)).
SYSTEM_ORG_ID = "orgsystem000"


@event.listens_for(Session, "before_flush")
def _stamp_org_in_tests(session, flush_context, instances):
    """Mirror of backend.db._stamp_org, but on the base Session class so the
    tests' patched sessionmaker stamps org_id too."""
    org = get_current_org()
    if org is None:
        return
    for obj in session.new:
        if hasattr(obj, "org_id") and getattr(obj, "org_id", None) is None:
            obj.org_id = org


@pytest.fixture(autouse=True)
def _system_org_context():
    set_current_org(SYSTEM_ORG_ID)
    yield
    set_current_org(None)
