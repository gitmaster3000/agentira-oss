# Task graph — child tasks, dependencies, milestones (AP-496)

Technical reference for the project-management layer added in AP-496. User-facing
docs live in the frontend repo: `docs/roadmap.md`.

## Model

| Thing | Storage | Rule |
|---|---|---|
| Child task | `tasks.parent_id` (self-FK, nullable, indexed) | same project, no cycles |
| Dependency | `task_dependencies` row: `(project_id, task_id, depends_on_id)` | same project, no self-edge, no cycles, unique per pair |
| Milestone | `milestones` row; tasks point at it via `tasks.milestone_id` | milestone must be in the task's project |

`task_id` **waits on** `depends_on_id`. A task is *blocked* when at least one thing
it depends on is not in the `done` status. Blocked is derived on read — there is no
stored flag to go stale.

Milestone progress is likewise derived: `done / total` over the tasks pointing at
the milestone. `Milestone.status` (`planned | achieved | missed`) is a human label
and is deliberately independent of that number.

Both new tables are listed in `backend/db.py::_ORG_SCOPED_TABLES`, so they get an
`org_id` column, the `org_iso` RLS policy and app-role grants like every other
tenant table. Columns are added by the idempotent migration steps in
`run_migrations()` (`tasks.parent_id`, `tasks.milestone_id` plus their indexes);
there is no Alembic in this codebase.

## Layering

- `backend/repos/task_graph.py` — all SQL. Rollups (`subtask_counts`,
  `milestone_counts`, `neighbor_tasks`) are batched: one grouped query per board,
  never one per row. Do not add a per-task query here.
- `backend/task_graph.py` — the rules: `validate_parent`, `add_dependency`
  (cycle check), `annotate_blocking`, milestone CRUD. Raises `GraphError`
  (a `ValueError` subclass) for invalid mutations; the REST layer maps that to
  **400**, and plain `ValueError` to 404.
- `backend/tasks.py::TaskService` — `update()` accepts `parent_id` / `milestone_id`
  (`""` detaches), `delete()` calls `task_graph.on_task_deleted` first.

### Cycle checks

Dependencies: the new edge is `task → blocker`; the graph already contains the
rest. A cycle exists iff `blocker` can already reach `task`, so `_reaches()` does
one DFS over `edges_for_project` before inserting.

Parents: walk `parent_id` upward from the proposed parent (`ancestor_ids`, bounded
by `MAX_DEPTH = 50`) and reject if the task itself appears.

## Deletion semantics

Deleting a task drops every dependency edge on either end and **orphans** its
children (`parent_id → NULL`) — a subtask usually still needs doing. Deleting a
milestone unlinks its tasks (`milestone_id → NULL`) and keeps them. Neither
delete cascades into real work.

## REST

| Method | Path | Notes |
|---|---|---|
| GET | `/api/projects/{id}/dependencies` | all edges in the project |
| POST | `/api/projects/{id}/dependencies` | `{task_id, depends_on_id}`; idempotent, 400 on cycle/self/cross-project |
| DELETE | `/api/projects/{id}/dependencies/{dep_id}` | |
| GET/POST | `/api/projects/{id}/milestones` | POST `{title, description?, due_date?, color?}` |
| PATCH/DELETE | `/api/projects/{id}/milestones/{milestone_id}` | PATCH takes any of title/description/due_date/status/color |
| GET | `/api/tasks/{id}/subtasks` | direct children, each with its own rollup |
| PATCH | `/api/tasks/{id}` | now also `parent_id`, `milestone_id` (`""` detaches) |
| POST | `/api/tasks` | now also accepts `parent_id`, `milestone_id` at create time |

Serialized tasks gained: `parent_id`, `milestone_id`, `subtasks {total, done}`,
`blocked_by[]`, `blocks[]`, `is_blocked`.

`GET /api/projects/{id}/roadmap` gained `dependencies[]`, real `milestones[]`,
`recent_completions[]` and `summary.blocked_tasks` / `summary.total_milestones`.
**Behavior change:** `milestones` used to mean "the last 10 done tasks" — that
list moved to `recent_completions`, and `milestones` is now the real table.

## MCP (agents)

An agent that can't read the plan can't work to it, so the same surface is on
the MCP server (`backend/mcp_server.py`), routed through thin `services`
delegations — all actor-scoped, same project-access checks as REST:

| Tool | Use |
|---|---|
| `get_roadmap(project_id, group_by="epic")` | the whole plan: dated tasks per epic/tag, dependency edges, `is_blocked` / `blocked_by` / `blocks` / `subtasks` per task, milestones with progress, summary counts |
| `list_subtasks(task_id)` | direct children |
| `list_dependencies` / `add_dependency` / `remove_dependency` | read + edit "waits on" edges |
| `list_milestones` / `create_milestone` / `update_milestone` / `delete_milestone` | milestone CRUD |
| `create_task(..., parent_id=, milestone_id=)` | create work already nested / already counted towards a milestone |
| `update_task(..., parent_id=, milestone_id=)` | re-parent or re-target later; `""` detaches |

`get_roadmap`'s docstring tells the agent the operative rule: a task with
`is_blocked: true` cannot be started until what it's `blocked_by` is done.

## Security

- Every graph endpoint is nested under `/projects/{id}` and calls
  `require_project_access(db, actor, project_id, "read"|"write")`, so project
  membership is checked before any row is touched — including the task-scoped
  `/tasks/{id}/subtasks`, which authorizes against the task's project.
- Cross-project edges and cross-project parents are rejected, so a member of
  project A cannot use the graph to link (and thereby enumerate) tasks in B.
- Both tables are org-scoped with RLS, so a graph row can never be read across
  tenants even if an id leaks.
- All input goes through Pydantic models and SQLAlchemy-bound parameters; no SQL
  is built from request strings. `due_date` is parsed with `datetime.fromisoformat`
  and rejected as 400 when malformed; `status` is checked against an allow-list.
- Graph walks are depth/visited bounded (`MAX_DEPTH`, `seen` sets) so a
  pre-existing or hand-crafted cycle can't spin a request.
- Every mutation writes an activity row (`task.dependency.add/remove`,
  `milestone.create/update/delete`) for the audit trail.

## Tests

`backend/tests/test_task_graph.py` — 20 tests: parenting + cycles + orphaning,
dependency add/remove/idempotency/cycles/cross-project, blocked-by transitions,
milestone CRUD + rollups + unlinking, roadmap payload, and a non-member access
check.
