"""Unit tests for AgentIRA services — RBAC model."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from backend.db import Base
from backend.models import Role, Permission, RolePermission, Status
from backend import services


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def test_db():
    """Create an in-memory SQLite DB and patch SessionLocal for every test."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    with patch("backend.services.SessionLocal", TestSession):
        # Seed defaults
        db = TestSession()
        services._seed_defaults(db)
        db.close()
        yield TestSession


# ── Project tests ───────────────────────────────────────────────────────

def test_create_project():
    p = services.create_project("TestProject", "desc")
    assert p["name"] == "TestProject"
    assert p["task_count"] == 0


def test_list_projects():
    services.create_project("A")
    services.create_project("B")
    assert len(services.list_projects()) == 2


def test_update_project():
    p = services.create_project("Old")
    updated = services.update_project(p["id"], name="New")
    assert updated["name"] == "New"


def test_delete_project():
    p = services.create_project("Delete Me")
    assert services.delete_project(p["id"]) is True
    assert services.get_project(p["id"]) is None


def test_project_scoping_admin_sees_all():
    """Admin should see all projects even if not a member."""
    p1 = services.create_project("P1")
    p2 = services.create_project("P2")
    services.create_profile("admin_user", role="admin")
    
    projects = services.list_projects(actor="admin_user")
    assert len(projects) == 2


def test_project_scoping_member_sees_only_assigned():
    """Member should only see projects they are assigned to."""
    p1 = services.create_project("P1")
    p2 = services.create_project("P2")
    
    services.create_profile("alice", role="member")
    services.add_project_member(p1["id"], "alice")
    
    # Alice should only see P1
    projects = services.list_projects(actor="alice")
    assert len(projects) == 1
    assert projects[0]["id"] == p1["id"]


def test_add_remove_project_member():
    p = services.create_project("P")
    prof = services.create_profile("bob", role="member")
    
    services.add_project_member(p["id"], "bob")
    p_updated = services.get_project(p["id"])
    assert "bob" in p_updated["members"]
    
    services.remove_project_member(p["id"], "bob")
    p_updated = services.get_project(p["id"])
    assert "bob" not in p_updated["members"]


# ── Task tests ──────────────────────────────────────────────────────────

def test_create_task():
    p = services.create_project("P")
    t = services.create_task(p["id"], "My Task")
    assert t["title"] == "My Task"
    assert t["status"] == "backlog"


def test_update_task():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    updated = services.update_task(t["id"], title="T2", priority="high")
    assert updated["title"] == "T2"
    assert updated["priority"] == "high"


def test_move_task_system():
    """System actor should bypass all permission checks."""
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    moved = services.move_task(t["id"], "todo", actor="system")
    assert moved["status"] == "todo"


def test_move_task_member():
    """Member should be able to move backlog -> todo (has permission)."""
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    # Alice needs to be member to create/interact in P (unless system created it, but auth checks generally check perms)
    # Actually current move_task only checks transition perms, but create_task enforces membership.
    # We'll use system to create task to avoid membership check there.
    t = services.create_task(p["id"], "T", actor="system") 
    
    moved = services.move_task(t["id"], "todo", actor="alice")
    assert moved["status"] == "todo"


def test_move_task_viewer_denied():
    """Viewer should NOT be able to move tasks."""
    services.create_profile("bob", role="viewer")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    with pytest.raises(PermissionError):
        services.move_task(t["id"], "todo", actor="bob")


def test_create_task_requires_membership():
    """Non-member cannot create task in project."""
    p = services.create_project("P")
    services.create_profile("outsider", role="member")
    
    with pytest.raises(PermissionError):
        services.create_task(p["id"], "Fail", actor="outsider")


def test_create_task_member_success():
    p = services.create_project("P")
    services.create_profile("insider", role="member")
    services.add_project_member(p["id"], "insider")
    
    t = services.create_task(p["id"], "Success", actor="insider")
    assert t["title"] == "Success"


def test_list_tasks_scoping():
    """Member sees tasks in their projects OR assigned to them."""
    p1 = services.create_project("P1")
    p2 = services.create_project("P2")
    
    services.create_profile("alice", role="member")
    services.add_project_member(p1["id"], "alice")
    
    t1 = services.create_task(p1["id"], "T1", actor="system")
    t2 = services.create_task(p2["id"], "T2", actor="system")
    
    # Alice sees T1 (member of P1), not T2
    tasks = services.list_tasks(actor="alice")
    ids = [t["id"] for t in tasks]
    assert t1["id"] in ids
    assert t2["id"] not in ids
    
    # Assign T2 to Alice -> Now she should see it
    services.update_task(t2["id"], assignee="alice")
    tasks = services.list_tasks(actor="alice")
    ids = [t["id"] for t in tasks]
    assert t1["id"] in ids
    assert t2["id"] in ids


def test_move_task_member_denied_close():
    """Member should NOT be able to move review -> done by default."""
    services.create_profile("alice", role="member")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    services.move_task(t["id"], "todo", actor="system")
    services.move_task(t["id"], "in_progress", actor="system")
    services.move_task(t["id"], "review", actor="system")
    with pytest.raises(PermissionError):
        services.move_task(t["id"], "done", actor="alice")


def test_move_task_admin_can_close():
    """Admin should be able to close tasks."""
    services.create_profile("admin_user", role="admin")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    services.move_task(t["id"], "todo", actor="system")
    services.move_task(t["id"], "in_progress", actor="system")
    services.move_task(t["id"], "review", actor="system")
    moved = services.move_task(t["id"], "done", actor="admin_user")
    assert moved["status"] == "done"


def test_delete_task():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    assert services.delete_task(t["id"]) is True
    assert services.get_task(t["id"]) is None


# ── Profile tests ───────────────────────────────────────────────────────

def test_create_profile():
    prof = services.create_profile("testuser", display_name="Test User", role="member")
    assert prof["name"] == "testuser"
    assert prof["role"] == "member"


def test_list_profiles_by_role():
    services.create_profile("a1", role="admin")
    services.create_profile("m1", role="member")
    admins = services.list_profiles(role="admin")
    assert all(p["role"] == "admin" for p in admins)


def test_update_profile_role():
    prof = services.create_profile("u1", role="viewer")
    updated = services.update_profile(prof["id"], role="member")
    assert updated["role"] == "member"


def test_delete_profile():
    prof = services.create_profile("del_me", role="member")
    assert services.delete_profile(prof["id"]) is True


# ── Permission grant/revoke ─────────────────────────────────────────────

def test_grant_profile_permission():
    """Extra permission granted directly to a profile."""
    prof = services.create_profile("extra_guy", role="member")
    services.grant_profile_permission(prof["id"], "transition:review:done")
    updated = services.get_profile(prof["id"])
    assert "transition:review:done" in updated["extra_permissions"]


def test_revoke_profile_permission():
    prof = services.create_profile("rev_guy", role="member")
    services.grant_profile_permission(prof["id"], "transition:review:done")
    assert services.revoke_profile_permission(prof["id"], "transition:review:done") is True
    updated = services.get_profile(prof["id"])
    assert "transition:review:done" not in updated["extra_permissions"]


def test_profile_extra_permission_allows_transition():
    """A member who gets extra 'transition:review:done' can close tasks."""
    prof = services.create_profile("closer", role="member")
    services.grant_profile_permission(prof["id"], "transition:review:done")
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    services.move_task(t["id"], "todo", actor="system")
    services.move_task(t["id"], "in_progress", actor="system")
    services.move_task(t["id"], "review", actor="system")
    moved = services.move_task(t["id"], "done", actor="closer")
    assert moved["status"] == "done"


# ── Comment & activity tests ────────────────────────────────────────────

def test_add_comment():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    c = services.add_comment(t["id"], "hello", actor="tester")
    assert c["action"] == "commented"
    assert c["detail"] == "hello"


def test_get_activity():
    p = services.create_project("P")
    t = services.create_task(p["id"], "T")
    services.add_comment(t["id"], "first")
    acts = services.get_activity(t["id"])
    assert len(acts) >= 2  # created + comment


# ── Board tests ─────────────────────────────────────────────────────────

def test_get_board():
    p = services.create_project("Board Project")
    services.create_task(p["id"], "T1")
    services.create_task(p["id"], "T2")
    board = services.get_board(p["id"])
    assert "columns" in board
    assert "backlog" in board["columns"]
    assert len(board["columns"]["backlog"]) == 2


# ── Status tests ────────────────────────────────────────────────────────

def test_list_statuses():
    statuses = services.list_statuses()
    names = [s["name"] for s in statuses]
    assert "backlog" in names
    assert "done" in names


# ── Role tests ──────────────────────────────────────────────────────────

def test_list_roles():
    roles = services.list_roles()
    names = [r["name"] for r in roles]
    assert "admin" in names
    assert "member" in names
    assert "viewer" in names


def test_admin_has_all_permissions():
    roles = services.list_roles()
    admin = next(r for r in roles if r["name"] == "admin")
    assert len(admin["permissions"]) > 0
    assert "transition:review:done" in admin["permissions"]


def test_member_lacks_close_permission():
    roles = services.list_roles()
    member = next(r for r in roles if r["name"] == "member")
    assert "transition:review:done" not in member["permissions"]
