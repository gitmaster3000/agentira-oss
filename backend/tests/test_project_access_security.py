"""Regression coverage for the project membership authorization boundary."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import backend.db as bdb
from backend import attachments, services
from backend.forge import services as forge_services
from backend.forge.models import Agent, Run, RunStatus
from backend.jwt_auth import create_token
from backend.models import Profile
from backend.rest_api import app


@pytest.fixture(autouse=True)
def test_db(pg):
    yield pg


def _scenario() -> tuple[dict, dict]:
    services.create_service_account("alice")
    services.create_service_account("mallory")
    project = services.create_project("Private", actor="alice")
    task = services.create_task(project["id"], "Secret task", actor="alice")
    return project, task


def test_non_member_cannot_discover_project_or_tasks():
    project, task = _scenario()

    assert services.list_projects(actor="mallory") == []
    assert services.list_tasks(actor="mallory") == []
    assert (
        services.list_tasks(
            project_id=project["id"],
            actor="mallory",
        )
        == []
    )

    with pytest.raises(PermissionError):
        services.get_project(project["id"], actor="mallory")
    with pytest.raises(PermissionError):
        services.get_task(task["id"], actor="mallory")


def test_assignment_does_not_grant_project_membership():
    project, task = _scenario()
    services.update_task(task["id"], assignee="mallory", actor="alice")

    assert services.list_tasks(actor="mallory") == []
    with pytest.raises(PermissionError):
        services.get_task(task["id"], actor="mallory")


@pytest.mark.parametrize("operation", ["update", "move", "comment", "delete"])
def test_non_member_cannot_mutate_task_by_out_of_band_id(operation):
    _, task = _scenario()

    with pytest.raises(PermissionError):
        if operation == "update":
            services.update_task(task["id"], title="stolen", actor="mallory")
        elif operation == "move":
            services.move_task(task["id"], "todo", actor="mallory")
        elif operation == "comment":
            services.add_comment(task["id"], "intrusion", actor="mallory")
        else:
            services.delete_task(task["id"], actor="mallory")


def test_non_member_cannot_read_activity_repos_epics_or_attachments():
    project, task = _scenario()
    epic = services.create_epic(project["id"], "Private epic", actor="alice")
    attachment = attachments.add(
        task_id=task["id"],
        filename="secret.txt",
        file_bytes=b"secret",
        content_type="text/plain",
        uploaded_by="alice",
    )

    for read in (
        lambda: services.get_activity(task["id"], actor="mallory"),
        lambda: services.get_project_activity(project["id"], actor="mallory"),
        lambda: services.list_project_repos(project["id"], actor="mallory"),
        lambda: services.get_epic(epic["id"], actor="mallory"),
        lambda: services.list_attachments(task["id"], actor="mallory"),
        lambda: services.get_attachment(attachment["id"], actor="mallory"),
    ):
        with pytest.raises(PermissionError):
            read()


def test_member_access_and_explicit_admin_wildcard_remain_supported():
    project, task = _scenario()

    assert services.get_project(project["id"], actor="alice")["id"] == project["id"]
    assert services.get_task(task["id"], actor="alice")["id"] == task["id"]
    assert services.get_project(project["id"], actor="system")["id"] == project["id"]
    assert services.get_task(task["id"], actor="system")["id"] == task["id"]


def test_membership_admin_is_separate_from_membership():
    project, _ = _scenario()

    with pytest.raises(PermissionError):
        services.add_project_member(project["id"], "mallory", actor="alice")
    services.add_project_member(project["id"], "mallory", actor="system")
    assert services.get_project(project["id"], actor="mallory")["id"] == project["id"]


def test_denial_is_generic_and_audited(caplog):
    project, _ = _scenario()

    with caplog.at_level(logging.WARNING, logger="agentira.auth"):
        with pytest.raises(
            PermissionError,
            match="Project resource not found or access denied",
        ):
            services.get_project(project["id"], actor="mallory")

    assert "project_access_denied" in caplog.text
    assert "mallory" in caplog.text


def test_rest_direct_ids_return_consistent_403_for_non_member(pg):
    project, task = _scenario()
    with bdb.SessionLocal() as db:
        mallory = db.query(Profile).filter(Profile.name == "mallory").one()
        token = create_token(
            mallory.name,
            mallory.id,
            ["member"],
            org_id=pg.org_id,
        )
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    for method, path, body in (
        ("get", f"/api/projects/{project['id']}", None),
        ("get", f"/api/tasks/{task['id']}", None),
        ("patch", f"/api/tasks/{task['id']}", {"title": "stolen"}),
        ("post", f"/api/tasks/{task['id']}/comment", {"comment": "stolen"}),
        ("get", f"/api/tasks/{task['id']}/activity", None),
        ("get", f"/api/projects/{project['id']}/attachments", None),
        ("get", f"/api/projects/{project['id']}/repos", None),
    ):
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, (path, response.text)
        assert response.json() == {
            "detail": "Project resource not found or access denied",
        }


def test_run_lists_and_direct_run_ids_are_project_scoped():
    project, _ = _scenario()
    with bdb.SessionLocal() as db:
        alice = db.query(Profile).filter(Profile.name == "alice").one()
        agent = Agent(
            id=alice.id,
            profile_id=alice.id,
            name="alice-agent",
            executor_type="http",
        )
        run = Run(
            agent_id=agent.id,
            project_id=project["id"],
            status=RunStatus.COMPLETED,
            artifacts_json='[{"url":"secret","kind":"report","label":"secret"}]',
        )
        db.add_all([agent, run])
        db.commit()
        run_id = run.id

    assert forge_services.list_runs(actor="mallory") == []
    with pytest.raises(PermissionError):
        forge_services.get_run(run_id, actor="mallory")
    assert forge_services.get_run(run_id, actor="alice")["id"] == run_id
