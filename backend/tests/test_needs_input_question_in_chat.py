"""AP-509: a needs_input question lands in the task chat, answerable there.

When an agent finishes with outcome=needs_input, its question is posted into
the agent's task chat as an AskUserQuestion card (clickable options when the
agent gave any, free text always), and the "needs input" notification links
straight to that chat so the human answers where the conversation lives.
"""

from __future__ import annotations

import json

import pytest

from backend import services as core_services
from backend.forge import services as forge_services
from backend.forge.models import AgentMessage, ForgeRuntime, RuntimeStatus


@pytest.fixture
def task_run(pg, seed_admin):
    with forge_services._session() as db:
        rt = ForgeRuntime(daemon_id="qd", provider="claude", binary_path="/tmp/c",
                          status=RuntimeStatus.ONLINE)
        db.add(rt)
        db.commit()
        rt_id = rt.id
    project = core_services.create_project("Questions", actor="system")
    task = core_services.create_task(project["id"], "pick a colour")
    agent = forge_services.create_agent(name="Asker", executor_type="cli", runtime_id=rt_id)
    run = forge_services.create_run(agent_id=agent["id"], task_id=task["id"],
                                    project_id=project["id"])
    return {"run_id": run["id"], "agent_id": agent["id"], "task_id": task["id"]}


def _chat(agent_id, task_id):
    with forge_services._session() as db:
        return (db.query(AgentMessage)
                  .filter(AgentMessage.agent_id == agent_id,
                          AgentMessage.scope_key == f"task:{task_id}")
                  .all())


def test_question_with_options_is_posted_to_task_chat(task_run):
    res = forge_services.finish_run(task_run["run_id"], outcome="needs_input",
                                    summary="Which colour should the button be?",
                                    options=["Blue", "Green"])
    assert res["ok"] is True

    [msg] = _chat(task_run["agent_id"], task_run["task_id"])
    assert msg.tool_name == "AskUserQuestion"
    assert msg.run_id == task_run["run_id"]
    payload = json.loads(msg.tool_input)
    assert payload == {"questions": [{
        "question": "Which colour should the button be?",
        "options": [{"label": "Blue"}, {"label": "Green"}],
    }]}


def test_question_without_options_still_shows_in_chat(task_run):
    forge_services.finish_run(task_run["run_id"], outcome="needs_input",
                              summary="What's the brand colour?")
    [msg] = _chat(task_run["agent_id"], task_run["task_id"])
    assert json.loads(msg.tool_input)["questions"][0] == {
        "question": "What's the brand colour?", "options": []}


def test_other_outcomes_post_nothing_to_chat(task_run):
    forge_services.finish_run(task_run["run_id"], outcome="blocked", summary="no creds")
    assert _chat(task_run["agent_id"], task_run["task_id"]) == []


def test_needs_input_notification_opens_the_task_chat(task_run):
    from backend.models import Notification
    forge_services.finish_run(task_run["run_id"], outcome="needs_input",
                              summary="Which colour?")
    with forge_services._session() as db:
        links = {n.link for n in db.query(Notification)
                 .filter(Notification.type == "agent.needs_input").all()}
    assert links == {f"/chat?agent={task_run['agent_id']}&scope=task:{task_run['task_id']}"}
