# Loop v1 — self-sufficient plan → build → verify → merge

Date: 2026-09-25 · Branch: `main-rsi` · Target: local stack only

## 1. Goal

Agents run the **whole** scrum cycle, continuously: the Conductor keeps the
project's direction, creates and prioritises epics, plans sprints, breaks
epics into tasks, dispatches agents, reviews, **verifies by running the
project's tests itself**, merges into the repo's base branch, runs the sprint
review, and starts the next sprint — every step visible in Agentira.

The human never has to act for the loop to proceed. They steer when they want
to: ask the Conductor questions in chat, edit anything (direction, epics,
tasks, priorities), or intervene on a task. They read an **executive
summary** of the work.

First proving ground: the **Agentira Platform** project building itself,
merging into `main-rsi`, on the local stack.

### Success criteria (acceptance test)

1. Starting from the project's current state and no human action, the
   Conductor (Opus 5.5) writes or refreshes the project's **direction**, picks
   or creates 1–3 epics for the sprint, and breaks them into tasks with DoD
   and links.
2. Tasks are assigned, dispatched, implemented, reviewed; the daemon merges
   each approved branch, runs the project's verify command on the merged
   tree, and pushes to `origin/main-rsi` only if it passes; a failure goes
   back to the implementer with the test output.
3. Tasks reach `done`, the next task starts, and when the sprint's work runs
   dry the Conductor plans the next sprint — no human click anywhere.
4. An executive summary is published per sprint and shown on the Conductor
   page: shipped (verified), in progress, blocked/risks, decisions the human
   may want to make, next sprint plan.
5. A human edit (e.g. reprioritising an epic, editing direction) is honoured
   by the next planning turn; a human question in the Conductor chat is
   answered from Agentira's data.
6. Every decision appears on the task/epic activity or the Conductor page
   with its reason. Nothing reports "dispatched"/"online" unless it is.
7. Nothing is ever pushed to any branch other than the repo's base branch
   (`main-rsi`) or task branches.

## 2. What exists (kept)

- Deterministic queue tick + event-driven `tick_agent` (conductor.py).
- LLM planning turn per managed project, recorded as `PlanningTurn`.
- Workflow driver (workflow.py): in_progress → review (reviewer role,
  dispatched) → integrate → done; bounce + rejection hand-back with shared
  budget; explicit `transition_events` idempotency (AP-402 fixed).
- Typed review verdicts (`submit_review`) as `human_approval` evidence.
- Daemon integrate: lock-guarded `merge --no-ff` in a temp worktree off the
  shared bare clone, push, result posted back.
- Durable dispatch outbox, reconciler, progress watchdog.

## 3. What breaks the loop today (spike, 2026-09-25)

| # | Break | Evidence |
|---|---|---|
| B1 | Assigning a task (human or planner) creates a `READY` run awaiting a manual Start; the picker counts `READY` as live → task never dispatched. | AP-402: READY run since 2026-07-06, every tick `no_eligible_task`. |
| B2 | Three `Conductor` profiles (one per org); planning, config, and active-flag lookups use `.first()` → a system-org Conductor on a dead runtime row. Turns queue, expire after 300s, still shown "dispatched". | backend log `Dispatch queued in outbox: no daemon online … agent=a532d1cc1f51`; daemon received nothing. |
| B3 | Integrate target is hardcoded `main` in system YAML; repo `default_branch` ignored. | workflow.py `IntegrateSpec.target_branch = "main"`. |
| B4 | No platform-run verification. Gates off; `github_pr`/`ci` providers need GitHub App creds → unknown. "Verified" = an LLM said approve. | gates-and-evidence.md; project `gates_enabled=false`. |
| B5 | Status lies: turn "dispatched" when undelivered, stale runtime row "online", planning card "undefined task(s)". | Conductor page. |
| B6 | Conductor is not a member of Agentira Platform → its MCP writes are refused. | members list; prior Conductor chat "access denied". |
| B7 | The workflow driver is unwired: since 2026-07-09 (#204) `finish_run` no longer calls `advance_after_run`, and `/daemon/integration-result` ignores results. No run advances any task. | services.py finish_run comment; router.py `daemon_integration_result`. |

## 4. Design

Nine small components. Each is independently testable; none adds a new
subsystem.

### C0 — Re-enable the workflow driver deliberately (B7)

- `finish_run`: on outcome `succeeded`, call `workflow.advance_after_run`
  (never raises; still no-ops unless the project has `workflow_enabled`).
- `/daemon/integration-result` calls `workflow.complete_integration`.
- This is the "reviewed and re-enabled deliberately" condition from #204: it
  lands together with C5 (merge only into the repo's base branch) and C6
  (merge only after the project's tests pass on the merged tree).


### C1 — Dispatch: READY is startable for conductor-managed agents (B1)

- `pick_next_unblocked`: a task whose latest run is `READY` **and** belongs to
  this agent is eligible (it is a prepared draft, not work in flight).
  `_ACTIVE_RUN_STATUSES` drops `READY`; `_agent_in_flight_count` already
  excludes it.
- The tick already calls `schedule_task_run`, which reuses the existing
  `READY` row (`prepare_task_run` returns it) and starts it. No new path.
- Manual-assignment UX (human sees READY, clicks Start) is unchanged for
  agents that are **not** conductor-managed.
- Tick writes a task activity line on dispatch: "Conductor dispatched to
  implementer-1 (priority critical, oldest assigned todo)".

### C2 — One Conductor per org, resolved by org (B2)

- New `conductor_for_org(db, org_id) -> Profile | None` in conductor.py. Every
  lookup that today does `Profile.name == "Conductor"` `.first()` —
  planning turn, daily report, progress check, sprint review,
  `get_conductor_config`, `_conductor_active` — takes an `org_id` and uses it.
- `_managed_projects` returns `(project_id, name, org_id)`; each project's
  planning turn is dispatched to **its org's** Conductor.
- `get_or_create_conductor` binds a runtime only if that runtime is currently
  connected (C4), never "the first claude runtime row".
- Orgs with no managed projects produce no turns (the system org's Conductor
  stays idle, harmlessly).

### C3 — Conductor can act on the projects it manages (B6)

- When a project becomes managed (any conductor-enabled agent bound to it),
  its org's Conductor is added as a project member — visible in the members
  list, removable by a human (then planning for that project is skipped with
  reason "Conductor is not a member").
- Done in the planning-turn preflight (idempotent), not a migration.

### C4 — Honest delivery and liveness (B2, B5)

- A runtime is **live** only while the WS hub holds a connected daemon that
  registered it (`hub.is_runtime_live(runtime_id)`); API responses derive
  `online`/`offline` from that, not from the stored `status` column.
- Before sending any Conductor turn (planning, sprint planning, progress
  check, sprint review, daily report), preflight: the Conductor's runtime is
  live. If not, the PlanningTurn is recorded `undelivered` with reason
  "Conductor's runtime is offline" and nothing is queued.
- If a queued Conductor dispatch later expires in the outbox, its PlanningTurn
  (matched by `turn:{id}` scope key) flips to `undelivered` with reason
  "no daemon picked it up".
- UI shows `dispatched` / `undelivered` / `skipped` / `error` literally; fix
  the planning card's "undefined task(s)" text.

### C5 — Merge into the repo's base branch (B3)

- `IntegrateSpec.target_branch` default becomes `""` meaning "the task's repo
  `default_branch`" (primary repo when the task names none). The system YAML
  drops the literal `main`.
- Resolved target is written on the `integration_requested` driver decision
  so the activity says "merging AP-123 into main-rsi".
- Daemon refuses an integrate frame whose target is empty (no silent `main`
  fallback in `core.py`).
- The **source** branch is the task's work branch (`task.branch`), never the
  approving reviewer run's own worktree branch (AP-520). The run's branch is a
  fallback only when no other agent succeeded on the task before it.
- `task.branch` follows the succeeded work run when it was pinned to the
  branch of an earlier run that never succeeded (AP-521). Branches no run
  produced (human/PR links) are never overwritten.

### C6 — Platform verification on the merged tree (B4)

- New project setting **`verify_cmd`** (text; Project Settings → General,
  plain-language label "Command that proves the project works").
- Daemon integrate becomes **merge → verify → push**:
  1. merge task branch into target in the temp worktree (as today);
  2. run `verify_cmd` there (shell, timeout `verify_timeout_minutes`,
     default 30), capture exit code + last 200 lines;
  3. exit 0 → push; non-zero or timeout → do not push, abort, clean up.
  4. post `{ok, reason, verify: {exit_code, duration_s, log_tail}}`.
- Backend `complete_integration` records a `gate_evaluations` row
  `evidence:tests` with that snapshot, and a task comment with the verdict
  and log tail.
- Failure → the existing rejection hand-back path: task back to
  `in_progress`, implementer re-dispatched with the log tail as the
  corrective context; shares the bounce budget; exhausted → needs-attention.
- Empty `verify_cmd` on a workflow-enabled project → merge refused with
  "no verify command configured" (unknown blocks — same invariant as the
  evidence engine).
- Verification order for a task: reviewer's typed approval (existing) →
  merged-tree tests (new) → push. Both recorded as evidence.
- For Agentira: `verify_cmd = scripts/verify.sh`, committed in this work:
  creates a venv from `requirements-dev.lock` with uv, runs
  `pytest backend/tests -q -n 4`, then `npm ci` + `vitest run` + `vite build`
  in `frontend/`. Docker must be available on the daemon host (testcontainers).

### C7 — Direction + sprint planning: the Conductor owns epics

- New project field **`direction_md`** (Project Settings → General, label
  "Goals & direction"): what the project is for and its current priorities,
  in plain language. Human-editable; the Conductor may update it via MCP
  `update_project` (which gains `direction_md`), and every change is an
  activity entry.
- New LLM turn **sprint planning** (`run_sprint_planning_turn`, prompt
  `templates/conductor/sprint_planning.md`), one per managed project. Facts:
  direction, epics (status, open/done counts), top backlog, last executive
  summary, recent failures. The Conductor:
  1. drafts `direction_md` if empty, from the repo's README/vision docs and
     the project description (writes it, says so in the summary);
  2. creates epics the direction calls for (`create_epic`) and closes epics
     whose tasks are all done;
  3. commits 1–3 epics to the sprint by setting them `in_progress` (epics in
     `backlog` are the parking lot; a human may move them either way);
  4. breaks every `in_progress` epic with no open tasks into 3–8 tasks
     (`create_task` with `epic_id`, DoD with ≥1 product-level check,
     priority; `add_dependency` for order).
- Triggers: daily after the sprint review, **and** when the queue runs dry —
  the regular planning turn finds no unassigned/backlog/todo work and no live
  runs in the project → it fires sprint planning (at most once per
  `sprint_min_interval_hours`, default 4, recorded as a PlanningTurn with
  trigger `queue_dry`).
- Epic → `done` when all its tasks are done (deterministic, in the driver's
  done-handler), with an epic comment listing what shipped.
- New work also enters from agents: implementer/reviewer prompts (config)
  allow `create_task` into **backlog** for discovered follow-ups, linked
  `relates_to` the source task. The planning turn promotes backlog as today.

### C8 — Executive summary and human steering

- The sprint review prompt (config) becomes an **executive summary** with
  fixed sections: Shipped (verified), In progress, Blocked / risks, Decisions
  you may want to make, Next sprint. Still published as a `sprint-review`
  task (existing) and additionally stored on the PlanningTurn so the
  Conductor page shows the latest one at the top.
- Human steering needs no new mechanism: edits are facts the next turn reads;
  the Conductor's project chat (`chat:project:<id>`) answers questions — its
  system prompt (config) tells it to answer from Agentira via MCP and to
  record any decision it makes as a comment on the affected epic/task.

### Transparency (cross-cutting)

Every loop action leaves a line a non-engineer can read, on the task or epic:
dispatched (C1), planning decisions (existing), direction/epic changes and breakdown (C7), hand-off /
bounce / hand-back (existing), merge target (C5), verification verdict (C6),
done. The Conductor page shows turn delivery states (C4).

## 5. Configuration for the proving run (no code)

- Conductor: claude runtime, `claude-opus-5-5` (done 2026-09-25).
- Conductor-managed agents on Agentira Platform: implementer-1 (Opus 5.5),
  implementer-2, senior-reviewer, reviewer, Documentation Expert. Local-model
  agents (qwen/openclaw) not conductor-enabled for v1.
- Repo `agentira`: remote `gitmaster3000/agentira-oss`, `default_branch
  main-rsi` (done). Pushes use the daemon machine's git login.
- Project: `workflow_enabled` on, `verify_cmd = scripts/verify.sh`,
  `direction_md` left empty so the Conductor drafts it (acceptance step 1).
- Daemon: editable install from this repo (done), so daemon fixes apply on
  restart.

## 6. Error handling

- Every component fails closed and visibly: undelivered turn, missing verify
  command, verify failure, missing membership, no live runtime — each is a
  recorded status + human-readable reason, never a silent no-op.
- Budgets: existing bounce/rejection budget (max attempts in window) caps
  verify-fail ping-pong; exhausted → needs-attention notification.
- Integrate lock (existing) serialises merges per repo, so two tasks never
  verify/push the same base concurrently; the second merges on top of the
  first's pushed result.

## 7. Testing

TDD per component, Postgres fixtures (`pg`, `seed_admin`):

- C0: `finish_run(succeeded)` on a workflow-enabled project advances the
  task; integration-result `ok` moves review → done.

- C1: agent with a READY run on an assigned todo task is picked; manual
  (non-managed) agent is not auto-started.
- C2: two orgs each with a Conductor; planning turn for org B's project goes
  to org B's Conductor; config read per org.
- C3: preflight adds membership once; removed membership → skip with reason.
- C4: offline Conductor runtime → turn `undelivered`, send not called;
  outbox expiry of a `turn:` scope flips it `undelivered`; runtime reads
  online only with a live hub registration.
- C5: target resolves to repo `default_branch`; empty target refused by daemon.
- C6 (daemon, pytest with temp git repos): pass → pushed; fail → not pushed,
  log tail returned; timeout → not pushed. Backend: failing verify → hand-back
  with log tail; missing verify_cmd → refused.
- C7: in_progress epic with no open tasks appears in sprint facts; queue-dry
  planning fires sprint planning once per interval; epic done when all tasks
  done; `update_project(direction_md=…)` via MCP writes an activity entry.
- C8: sprint review stores the summary on its PlanningTurn; latest summary
  returned by the conductor status endpoint.
- Acceptance: §1 run live on the local stack, recorded in the spec's
  follow-up notes.

## 8. Out of scope (next specs)

- Context packs for long horizons (epic/links/milestones/handover notes →
  per-dispatch bundle).
- Agent-to-agent and group channels.
- MCP token/memory efficiency (`list_tasks` returns 940 KB today).
- Human sign-off (option B) — exists on `feat/human-signoff-merge-evidence`,
  merge later after review.
- UI redesign; board cleanup; stale `in_progress`/`review` tasks with no live
  run; agent memory path pointing at `/root/.agentira`.
