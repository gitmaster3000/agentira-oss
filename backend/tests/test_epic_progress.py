from backend import services


def test_epic_done_when_last_task_done(pg):
    services.create_service_account("u1")
    p = services.create_project("E", actor="u1")
    e = services.create_epic(p["id"], "Ep", actor="u1")
    services.update_epic(e["id"], status="in_progress", actor="u1")
    t1 = services.create_task(p["id"], "a", epic_id=e["id"], actor="u1")
    t2 = services.create_task(p["id"], "b", epic_id=e["id"], actor="u1")
    services.move_task(t1["id"], "done", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "in_progress"
    services.move_task(t2["id"], "done", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "done"


def test_epic_close_activity_lists_shipped_keys(pg):
    services.create_service_account("u1")
    p = services.create_project("E", actor="u1")
    e = services.create_epic(p["id"], "Ep", actor="u1")
    services.update_epic(e["id"], status="in_progress", actor="u1")
    t1 = services.create_task(p["id"], "a", epic_id=e["id"], actor="u1")
    services.move_task(t1["id"], "done", actor="u1", skip_gates=True)

    from backend.services import _session
    from backend.models import Activity
    with _session() as db:
        details = [a.detail for a in db.query(Activity)
                   .filter(Activity.project_id == p["id"]).all()]
    key = services.get_task(t1["id"])["key"]
    assert any(d.startswith("All tasks done — epic closed. Shipped:") and key in d
               for d in details)


def test_epic_closed_via_workflow_move(pg):
    # The workflow driver's complete_integration advances a task to done via
    # move_task(actor="workflow", skip_gates=True, record_transition=False).
    # That same shared path must close the epic.
    services.create_service_account("u1")
    p = services.create_project("E", actor="u1")
    e = services.create_epic(p["id"], "Ep", actor="u1")
    services.update_epic(e["id"], status="in_progress", actor="u1")
    t1 = services.create_task(p["id"], "a", epic_id=e["id"], actor="u1")
    services.move_task(t1["id"], "done", actor="workflow",
                       skip_gates=True, record_transition=False)
    assert services.get_epic(e["id"])["status"] == "done"


def test_reopened_epic_not_reclosed_until_new_done(pg):
    services.create_service_account("u1")
    p = services.create_project("E", actor="u1")
    e = services.create_epic(p["id"], "Ep", actor="u1")
    services.update_epic(e["id"], status="in_progress", actor="u1")
    t1 = services.create_task(p["id"], "a", epic_id=e["id"], actor="u1")
    services.move_task(t1["id"], "done", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "done"

    # Human reopens; all tasks still done, but no task transitioned → stays open.
    services.update_epic(e["id"], status="in_progress", actor="u1")
    assert services.get_epic(e["id"])["status"] == "in_progress"

    # A fresh task→done transition re-closes it.
    services.move_task(t1["id"], "todo", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "in_progress"
    services.move_task(t1["id"], "done", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "done"


def test_epic_not_closed_with_open_tasks(pg):
    services.create_service_account("u1")
    p = services.create_project("E", actor="u1")
    e = services.create_epic(p["id"], "Ep", actor="u1")
    services.update_epic(e["id"], status="in_progress", actor="u1")
    t1 = services.create_task(p["id"], "a", epic_id=e["id"], actor="u1")
    services.create_task(p["id"], "b", epic_id=e["id"], actor="u1")
    services.move_task(t1["id"], "done", actor="u1", skip_gates=True)
    assert services.get_epic(e["id"])["status"] == "in_progress"
