# Feature: Delete a project (full cascade)

> **Audience.** Anyone removing a project, plus engineers maintaining the
> delete path. Deleting a project is permanent and removes **everything**
> inside it.

---

## 1. What a user sees

Deleting a project removes the project and all of its work in one action:

- every **task** and **epic** in the project
- every **run** (agent execution) for those tasks or the project
- every **chat** (project chat + per-task chats) and its messages
- every **file** attached to the project or its tasks — both the database
  records and the actual files on disk
- project **members** and the project's **activity** history
- the project's **repo connections**

This cannot be undone. There is no archive or trash — once deleted, the work
is gone. Agents whose default project was the deleted one simply lose that
default (the agent itself is **not** deleted).

## 2. How to delete

- **REST:** `DELETE /api/projects/{project_id}` → `{ "ok": true }` (404 if the
  project doesn't exist).
- **MCP tool:** `delete_project(project_id)` → returns `true` on success,
  `false` if the project wasn't found.

## 3. How it works (technical)

Entry point: `backend.services.delete_project(project_id)`.

A project owns rows across two module boundaries. The core models
(`Task`, `Epic`, `ProjectMember`, `Activity`, project/task `Attachment` rows)
have SQLAlchemy `cascade="all, delete-orphan"` relationships, so they are
removed automatically when the `Project` row is deleted. But several FKs have
**no** cascade and would block (or orphan rows on) a plain delete:

| Table / column | Why it blocks | Handled by |
| --- | --- | --- |
| `forge_runs.project_id` / `forge_runs.task_id` | FK with no cascade → `ForeignKeyViolation` | `forge/repos/project_purge.py` deletes the runs first |
| `project_repos.project_id` | FK with no cascade | `repos/projects.py::delete_project_repos` |
| `profiles.default_project_id` | FK with no cascade | `repos/projects.py::clear_default_project_pointers` (set NULL) |
| `forge_agents.default_project_id` | FK with no cascade | `forge/repos/project_purge.py` (set NULL) |
| Chat rows (`forge_conversations`, `forge_messages`, `forge_queued_messages`) | keyed by string `scope_key`, no FK → would orphan | `forge/repos/project_purge.py` deletes by scope_key |
| Attachment files on disk | ORM cascade drops rows only | `attachments.py::purge_project_files` (`rmtree` the storage dirs) |

Order in `delete_project`:

1. `attachments.purge_project_files` — remove the on-disk storage dirs for the
   project and each task.
2. `project_purge.purge_project_data` — delete forge runs (by project or task),
   delete chat rows for scopes `chat:project:<pid>`, `task:<tid>`, and legacy
   `run:<id>`, and NULL out `forge_agents.default_project_id`.
3. `delete_project_repos` + `clear_default_project_pointers` — clear the
   remaining FK blockers.
4. `db.delete(project)` — ORM cascade removes tasks/epics/members/activities
   and attachment rows; commit.

Chats use string scope keys (see `forge/services.py::conversation_scope_key`):
`task:<task_id>`, `chat:project:<project_id>`, and the legacy `run:<run_id>`.
The purge enumerates all of these for the project being deleted.

### Layering

Runs and chats are forge-owned, so the SQL that removes them lives in
`backend/forge/repos/project_purge.py`. Core-owned blockers (`project_repos`,
`Profile.default_project_id`) live in `backend/repos/projects.py`. The core
service `delete_project` composes both — it does not inline the SQL.

## 4. Tests

- Unit: `backend/tests/test_delete_project.py` seeds a project with one of
  every owned row (task, member, two runs, repo, project + task chats, queued
  message, on-disk attachment) and asserts all of it — including the file on
  disk — is gone, the agent/profile default-project pointer is cleared, and the
  agent itself survives. Also covers the missing-project (`False`) case.
- Integration (Bruno): `bruno/mcp/10-project-delete/` creates a throwaway
  project + task, deletes the project via the `delete_project` MCP tool, and
  verifies it no longer resolves via `get_project`.

## 5. Manual test

See `docs/MANUAL_TEST_PLAN.md` → "Delete a project (cascade)".
