# Agentira — Manual Test Plan

End-to-end walkthrough for a fresh user / fresh project, exercising every
feature shipped in this Stop/Pause/Resume + run-investigation +
templates + artifacts + per-run-worktrees + multi-repo + project-page push.

**Time:** ~30 min if everything works. Stop at any failed step and note
which one — every step links to the PR/ticket it exercises.

---

## Phase 0 — Pre-flight (operator)

- [ ] `docker compose ps` — backend + mcp + frontend all `Up`.
- [ ] `agentira daemon status` — daemon process running.
- [ ] Daemon registered: open `https://localhost:5173/forge/runtimes` → at
      least one runtime online with a fresh (< 60s) heartbeat. If stale,
      `agentira daemon restart`.

If anything fails here, the rest of the plan won't run — fix infra first.

---

## Phase 1 — Signup + create your first project

1. **Signup as a new user**
   - Open `https://localhost:5173/signup`.
   - Submit name + email + password.
   - **Expect:** redirect to Studio dashboard; sidebar shows "Planning"
     section; no projects yet.

2. **Create a project**
   - Click "Create project" → name it `Smoke Test`, description "Manual
     test plan run".
   - **Expect:** redirect into the project, lands on `/overview`
     (not `/board`).
   - **Tests:** AP-130 (`Route index → overview`), proper landing page.

3. **Overview page**
   - **Expect:** quick-link tiles (Board / Backlog / Roadmap / Settings),
     status counts all zero, "No repos attached", "No members yet"
     (or just you), "Nothing yet" under Recent activity.

4. **Configure the project**
   - Click sidebar **Settings** (gear, bottom).
   - **General tab:** edit description; leave Primary repo blank for now;
     paste a tiny convention into Conventions:
     ```
     # Conventions
     Use ruff. Commit on a feature branch.
     ```
     Save.
   - **Expect:** "Saved" badge appears for 2s.
   - **Repos tab:** click → empty state.
     - Attach a repo: name=`primary`, repo_path=an absolute path to a real
       git checkout (e.g. `/tmp/demo-repo` — `git init` one first if you
       don't have one handy), default_branch=`main`, **check** "Mark as
       primary".
     - **Expect:** row appears with a "primary" star badge.
   - **Tests:** AP-121 (project_repos add), AP-130 (settings live with
     entity), project-page-and-settings PR.

5. **Add a task**
   - Sidebar → **Board**.
   - "New task" → title "Add a `hello.txt`", description "Create a file
     called hello.txt at the repo root with the content 'hello dogfood'".
   - Leave assignee blank (we'll assign in the next phase).
   - **Expect:** task lands in the `backlog` column.

---

## Phase 2 — First task, end-to-end (manual)

This is the loop you trust before turning on the Conductor.

1. **Move task to `todo`**
   - Drag the task from backlog → todo on the board.
   - **Expect:** column count updates; task animates.

2. **Assign an agent**
   - Click the task → assignee dropdown → pick a forge-managed agent
     bound to a runtime (e.g. `implementer-1` if you're on the local
     setup with claude online; otherwise create one in `/forge/agents`).
   - **Expect:** in `/forge/runs` you see a new run for that agent —
     **status is READY**, NOT running.
   - **Tests:** AP-129 (assignment lands READY, never auto-RUNNING).

3. **Review the prompt and click Start**
   - Open the Run detail page from `/forge/runs`.
   - **Expect:** the prepared prompt is shown editable (task title +
     description + DoD if any + run instructions).
   - Edit the prompt if you want (e.g. add "use a clear commit message").
   - Click **Start**.
   - **Expect:** status pill briefly shows `pending` then `running`.

4. **Watch it run**
   - Stay on the Run page. Don't poll-refresh.
   - **Expect:**
     - Events stream in real time (text + tool_use + tool_result rows
       appear without you reloading).
     - Status pill updates from `running` instantly (no 5s lag) — this is
       the AP-P4 WebSocket push.
     - Token counter and cost tick up.
   - **Tests:** WS run-status push.

5. **Let it finish**
   - **Expect:** status → `completed`, outcome badge (✅/⛔/etc.) from
     the agent's `finish_run` call. Diff panel shows the new file. The
     run produces a comment back on the task.

6. **Check the workdir**
   - In a terminal: `git -C <your-repo> worktree list`.
   - **Expect:** the per-run worktree is GONE (cleaned up on terminal
     complete). The per-run branch is also deleted from the source repo.
   - **Tests:** AP-123 (per-run worktrees + cleanup).

7. **Check the task**
   - Back in Studio → the task should show the agent's verdict comment in
     activity, and (if the agent registered one) the artifacts panel on
     the run shows links — PR, file, etc.
   - **Tests:** AP-125 + AP-126 (artifacts).

---

## Phase 3 — Stop / Pause / Resume (the reliability story)

Do these three back-to-back. Each is about 1 minute.

1. **Cancel mid-run**
   - Start a long-ish task (one that runs >10s). Same loop as Phase 2
     but task = "list every Python file in the repo, count lines, and
     report".
   - Once status is `running`, click **Stop** on the chat / Run page.
   - **Expect:**
     - Pill IMMEDIATELY shows `Cancelling…` (transient state).
     - Within 5s flips to `cancelled`.
     - No `⚠ execution failed` system message in the chat (cancel is not
       a failure).
     - `ps -ef | grep claude` — no claude process for that run.
     - Run page shows summary "Run cancelled by user."
   - **Tests:** AP-P1 (cancel handshake + SIGKILL fallback + cancelled
     flag), AP-P3 (transient state), AP-P4 (WS push), AP-P5 (process-
     group kill).

2. **Pause + Resume via chat**
   - Start a new task. Once running, click **Pause** on the Run page.
   - **Expect:** pill → `Pausing…` then `Paused` within 5s. Subprocess
     dies (`ps -ef | grep claude` empty).
   - On the same task scope in chat, send a message: "continue but skip
     step 2".
   - **Expect:** pill → `Resuming…` then `Running`. The agent picks up
     where it left off (via `claude --resume <session_id>`). Conversation
     continuity preserved.
   - **Tests:** AP-P3 transient states + auto-resume race fix + paused
     stays paused on tab switch.

3. **Tab-switch sanity**
   - Pause a run. Switch to another browser tab for ~30s. Come back.
   - **Expect:** still `Paused`. **NOT** running. (The flake the user
     originally reported.)

4. **Cancel from paused**
   - Pause a run. On the Run page (status=Paused), Stop button should be
     visible.
   - Click Stop.
   - **Expect:** pill → `Cancelling…` → `Cancelled`. Worktree cleaned up.
   - **Tests:** AP-P4 frontend "Cancel from paused" addition.

---

## Phase 4 — Failure paths

1. **Daemon crash recovery**
   - Start a task. While it's running, kill the daemon: `agentira daemon
     stop` (or `kill -9` the PID).
   - **Expect:** within ~2 min, the run flips to `failed` with error
     "Daemon offline — run reconciled as failed." Admin notification
     appears in the bell.
   - Restart daemon. Subsequent dispatches work normally.
   - **Tests:** AP-P2 (stale-run reconciler).

2. **Agent declares blocked**
   - Create a task with deliberately ambiguous spec ("do the thing").
   - Wait for the run to finish (the agent should call
     `finish_run(outcome="blocked", summary="…")`).
   - **Expect:** outcome badge = ⛔ Blocked on the run; the bell has a
     **high-priority** notification "Agent blocked task X: …". Linked
     to the task.
   - **Tests:** AP-36 (blocked notification).

3. **Run that fails its subprocess**
   - Set the agent's model to something invalid (`claude-foo-9000`) on
     /forge/agents.
   - Dispatch a task.
   - **Expect:** run fails fast; error message is the claude-code message
     ("There's an issue with the selected model…"), NOT a generic
     "subprocess exited with code 1". Admin notification fires.

4. **Auto-retry on transient crash** (skip unless you can simulate)
   - If a run dies with "subprocess exited with code 1" on the
     dispatch path: the backend re-dispatches up to 2 times within
     20 min on the same session.

---

## Phase 5 — Multi-repo per project (AP-121)

1. **Attach a second repo**
   - Project Settings → Repos tab → attach another repo, name=`frontend`,
     path=another local checkout.
   - **Expect:** two rows; `primary` still primary; `frontend` not.

2. **Create a task targeting the second repo**
   - Create a new task; in the task editor, set `repo_name=frontend`
     (CreateTask dialog dropdown — if not exposed yet, set via the task
     detail panel).
   - Assign to a forge agent. Dispatch.
   - **Expect:** the worktree the daemon materializes is off the
     `frontend` repo path, NOT the primary. Diff shows changes scoped to
     that repo.

3. **Task without `repo_name`**
   - Create another task; leave repo_name blank.
   - **Expect:** dispatches against the primary repo.

---

## Phase 6 — Concurrency (AP-123)

1. **Bump max_concurrent_runs**
   - On an agent (e.g. `implementer-1`), set `max_concurrent_runs=2` via
     the agent page or via PATCH `/api/forge/agents/{id}` body
     `{"max_concurrent_runs": 2}`.

2. **Dispatch two tasks at once**
   - Two tasks assigned to the same agent, both in `todo`. Hit Start on
     each (or `POST /api/forge/runs` if your UI doesn't let you).
   - **Expect:**
     - Both runs reach `RUNNING` simultaneously.
     - `git -C <repo> worktree list` shows two distinct paths under
       `agents/<id>/home/repos/<project>/run-<run_id_a>/` and
       `run-<run_id_b>/`.
     - Their diffs don't collide.

3. **Try to dispatch a third with cap=2**
   - Same agent, third concurrent dispatch.
   - **Expect:** rejected with "Agent at concurrency cap (2/2 task runs
     in flight)…". Set the task back to `todo` and wait for one to finish.

---

## Phase 7 — Conductor autopilot

1. **Enable the Conductor**
   - Go to `/forge/conductor`.
   - Toggle the master switch to **Active**.
   - Verify cadence: queue-tick 60s, planning 10 min, daily report 09:00
     UTC.

2. **Set up an autopilot agent**
   - Pick `implementer-1` (or any conductor-enabled agent).
   - Confirm `conductor_enabled=True` on its config.
   - Set `default_project_id=Smoke Test`.

3. **Drop a few todo tasks**
   - Create 3 tasks in `todo`, leave them unassigned. Vary priorities.
   - **Expect:** within 10 min, the Conductor's planning turn assigns
     them to conductor-enabled agents. Then the queue tick dispatches
     them (one at a time, since cap=1 by default).

4. **Watch the runs flow**
   - `/forge/runs` shows new runs appearing without you doing anything.
   - The Conductor page shows "Last tick" and "Last plan" timestamps
     updating.

5. **Click Stop on a dispatched-by-Conductor run**
   - **Expect:** same Cancelling… → Cancelled flow as Phase 3. The
     Conductor does NOT immediately re-dispatch (cancel was a deliberate
     human action).

---

## Phase 8 — Daily report (HTML)

1. **Trigger manually**
   - On `/forge/conductor`, click **Run daily report now** (admin
     button).
   - Wait ~30s for the Conductor LLM turn to finish.
   - **Expect:** "Last report" panel shows a generated HTML report.

2. **View the report**
   - Click the report → it renders as a formatted executive page (KPI
     cards, Wins / Blocked / Failing / Priorities sections).

3. **Download as PDF**
   - Click "Download PDF" on the report.
   - **Expect:** opens a print-styled standalone page in a new tab; the
     browser's Save-as-PDF produces a clean document.

---

## Phase 9 — MCP run-investigation (AP-107)

This one needs an agent or `bruno` to exercise — the MCP tools aren't
in the UI directly.

1. **Pick a finished run.** Note its `run_id` from `/forge/runs`.
2. **From an agent's chat** (or via the bruno collection), call:
   - `get_run(run_id=...)` → returns full status / outcome / tokens.
   - `get_run_events(run_id=..., limit=20)` → tool-call log.
   - `get_run_diagnostics(run_id=...)` → exit_code, stderr_tail, status_
     vs_outcome.
3. **From an agent that's NOT a member of the run's project**, call the
   same tools.
   - **Expect:** `{"error": "forbidden", "detail": "…not a member of
     project…"}`.

---

## Phase 10 — Templates (AP-3 + AP-4)

1. **Use a packaged template**
   - From a Python shell or via a bruno call to the not-yet-exposed
     internal endpoint:
     ```python
     from backend.template_loader import load_template, instantiate_project_from_template
     t = load_template("templates/production-readiness.yaml")
     instantiate_project_from_template(t, "Audit run #1", actor="admin")
     ```
   - **Expect:** new project appears named "Audit run #1" with
     `template_name = production-readiness`. Agent profiles for the
     template's agents exist (auditor, planner, etc.).

2. **Re-run with the same name (idempotency)**
   - Same command again.
   - **Expect:** no duplicate project; no duplicate agents.
     `created=False` in the return.

---

## Phase 11 — Cleanup

### Delete a project (cascade)

Setup so there's something to cascade: the Smoke Test project should already
have at least one task, one run, a chat, and an attached file from earlier
phases. If not, add a task, open its chat and send one message, and attach a
file.

- [ ] Note the project's task(s), run(s), chat(s), and attached file(s).
- [ ] Delete the Smoke Test project (Project Settings → Delete, or
      `delete_project` via MCP, or `DELETE /api/projects/{id}`).
- [ ] **Expect:** the call succeeds (`{"ok": true}` / `true`) and the project
      disappears from the project list.
- [ ] **Confirm full cascade — all of the following are gone:**
      - the project's tasks and epics no longer resolve.
      - its runs no longer appear in `/forge/runs`.
      - its chats (project chat + per-task chats) are gone.
      - attached files are removed (DB record **and** the file on disk under
        `data/attachments/` — check the volume).
      - `project_repos` for it are gone.
- [ ] **Confirm survivors:** the agent(s) still exist in `/forge/agents`;
      only their *default project* pointer was cleared. Nothing else crashes.
- [ ] Deleting a non-existent project id returns a 404 (REST) / `false` (MCP).

Exercises the project cascade-delete feature (`docs/feature-project-delete.md`).

---

## Known gaps (don't test, won't pass)

- **Docker / systemd / `docker run -d` containers** spawned by claude
  survive Stop. AP-83 Path B (container isolation) is the structural
  fix; not shipped.
- **TaskCreate dialog repo dropdown for multi-repo projects** —
  followup to AP-121 frontend; if you don't see it, set `repo_name` via
  the task detail panel.
- **AP-131** — Run defaults aren't editable from the UI yet (just an
  audit panel on /forge/settings). That's filed and intentional.

---

## What to file when something doesn't work

For each failing step:

1. Note the step number + what you expected vs got.
2. Snapshot the Run page if it's run-related.
3. `docker compose logs agentira-backend-1 --tail 200` and the daemon log
   `~/.agentira/daemon.log --tail 200`.
4. File as a task on `Agentira Platform` with `priority=high` and a clear
   reproduction.

Have fun. Bye 👋
