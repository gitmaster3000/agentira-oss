"""Per-project workflow prompt overrides — config, not code/PRs.

Covers:
- Resolution order: project override text > system template file > ''.
- REST GET returns every column/policy slug with system_default + effective +
  is_override, GET is authed but not admin-only (read), PUT is admin-only.
- Round-trip: PUT sets, GET reflects, PUT with empty clears.
- System templates on disk are never mutated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import services as core_services
from backend.forge import workflow
from backend.rest_api import app


@pytest.fixture
def client(seed_admin):
    admin_id, token = seed_admin
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    c.admin_id = admin_id
    yield c


def _project(client):
    return client.post("/api/projects", json={"name": "P"}).json()["id"]


# ── Resolution order (unit) ─────────────────────────────────────────────

def test_resolve_prompt_prefers_project_override_over_system_file():
    class P:
        id = "p1"
        workflow_prompts_json = json.dumps({"reviewer": "OVERRIDE TEXT"})
    assert workflow._resolve_prompt(P(), "reviewer") == "OVERRIDE TEXT"


def test_resolve_prompt_falls_back_to_system_file_when_no_override():
    class P:
        id = "p1"
        workflow_prompts_json = None
    text = workflow._resolve_prompt(P(), "reviewer")
    assert text  # system reviewer template ships in-tree
    assert text == workflow._load_prompt_file("reviewer")


def test_resolve_prompt_empty_override_falls_back_to_system():
    class P:
        id = "p1"
        workflow_prompts_json = json.dumps({"reviewer": "   "})  # whitespace-only
    assert workflow._resolve_prompt(P(), "reviewer") == \
        workflow._load_prompt_file("reviewer")


def test_malformed_prompt_json_is_ignored_not_fatal():
    class P:
        id = "p1"
        workflow_prompts_json = "not json"
    assert workflow._prompt_overrides(P()) == {}


def test_column_ui_details_surfaces_slug_and_override_flag():
    class P:
        id = "p1"
        workflow_prompts_json = json.dumps({"reviewer": "MY REVIEWER PROMPT"})
        workflow_roles_json = None
    flow = workflow.effective_workflow(P())
    ui = workflow.column_ui_details(flow, project=P())
    review = ui["review"]
    assert review["prompt_role"] == "reviewer"
    assert review["prompt_slug"] == "reviewer"
    assert review["prompt"] == "MY REVIEWER PROMPT"
    assert review["prompt_is_override"] is True
    # A column with no override still resolves to the system default.
    done = ui["done"]
    assert done["prompt_slug"] == "documentation"
    assert done["prompt_is_override"] is False
    assert done["prompt"] == workflow._load_prompt_file("documentation")


# ── REST GET ────────────────────────────────────────────────────────────

def test_get_workflow_prompts_lists_every_slug_with_defaults(client):
    pid = _project(client)
    r = client.get(f"/api/projects/{pid}/workflow/prompts")
    assert r.status_code == 200
    prompts = {p["slug"]: p for p in r.json()["prompts"]}
    # Role-derived + policy slugs are all present.
    for slug in ("reviewer", "documentation", "gate_bounce",
                 "rejection_handback"):
        assert slug in prompts, prompts.keys()
        assert prompts[slug]["system_default"]      # non-empty
        assert prompts[slug]["is_override"] is False
        assert prompts[slug]["effective"] == prompts[slug]["system_default"]
    # Reviewer's column linkage is exposed for the UI.
    assert "review" in prompts["reviewer"]["columns"]


# ── REST PUT round-trip + RBAC ──────────────────────────────────────────

def test_put_workflow_prompt_sets_override_and_get_reflects_it(client):
    pid = _project(client)
    r = client.put(f"/api/projects/{pid}/workflow/prompts/reviewer",
                   json={"text": "Custom reviewer prompt."})
    assert r.status_code == 200, r.text
    assert r.json()["is_override"] is True

    r2 = client.get(f"/api/projects/{pid}/workflow/prompts")
    slot = next(p for p in r2.json()["prompts"] if p["slug"] == "reviewer")
    assert slot["is_override"] is True
    assert slot["override"] == "Custom reviewer prompt."
    assert slot["effective"] == "Custom reviewer prompt."
    # System default stays visible for comparison in the UI.
    assert slot["system_default"] == workflow._load_prompt_file("reviewer")


def test_put_empty_text_clears_the_override(client):
    pid = _project(client)
    client.put(f"/api/projects/{pid}/workflow/prompts/reviewer",
               json={"text": "Custom."})
    r = client.put(f"/api/projects/{pid}/workflow/prompts/reviewer",
                   json={"text": ""})
    assert r.status_code == 200
    assert r.json()["is_override"] is False
    slot = next(p for p in client.get(
        f"/api/projects/{pid}/workflow/prompts").json()["prompts"]
                if p["slug"] == "reviewer")
    assert slot["is_override"] is False


def test_put_unknown_slug_400(client):
    pid = _project(client)
    r = client.put(f"/api/projects/{pid}/workflow/prompts/bogus_slug",
                   json={"text": "x"})
    assert r.status_code == 400


def test_put_workflow_prompt_requires_admin(client, pg):
    # Create a non-admin member profile + token in the same org.
    from backend.jwt_auth import create_token
    from backend.db import SessionLocal, privileged
    from backend.models import Profile, Role
    pid = _project(client)
    with privileged(), SessionLocal() as db:
        member_role = db.query(Role).filter(Role.name == "member").first()
        prof = Profile(name="alice", account_type="human",
                       roles=[member_role], org_id=pg.org_id,
                       password_hash="")
        db.add(prof)
        db.commit()
        member_token = create_token("alice", prof.id, ["member"],
                                    org_id=pg.org_id)
    c2 = TestClient(app)
    c2.headers["Authorization"] = f"Bearer {member_token}"
    r = c2.put(f"/api/projects/{pid}/workflow/prompts/reviewer",
               json={"text": "nope"})
    assert r.status_code == 403


# ── System templates on disk stay untouched ────────────────────────────

def test_system_template_files_are_not_mutated_by_override(client):
    pid = _project(client)
    reviewer_path = Path(workflow._PROMPTS_DIR / "reviewer.md")
    before = reviewer_path.read_bytes()
    client.put(f"/api/projects/{pid}/workflow/prompts/reviewer",
               json={"text": "Custom."})
    assert reviewer_path.read_bytes() == before
