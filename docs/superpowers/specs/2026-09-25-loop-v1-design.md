# Loop v1 — self-sufficient plan → build → verify → merge

Date: 2026-09-25 · Branch: `main-rsi` · Target: local stack only

## 1. Goal

A human steers **epics**. Agentira does the rest, continuously: breaks epics into
tasks, queues them, dispatches agents, reviews, **verifies by running the
project's tests itself**, merges into the repo's base branch, and picks the
next task — with every step visible in Agentira.

First proving ground: the **Agentira Platform** project building itself,
merging into `main-rsi`, on the local stack.

### Success criteria (acceptance test)

1. Human creates an epic in Agentira Platform and sets it to `in_progress`
   (epic statuses are `backlog | in_progress | done`; `in_progress` = "work on this").
2. With no further human clicks, within a few planning cycles:
   - the Conductor (Opus 5.5) creates tasks under it with DoD and links;
   - tasks are assigned, dispatched, implemented, reviewed;
   - the daemon merges each approved branch, runs the project's verify
     command on the merged tree, and pushes to `origin/main-rsi` only if it
     passes; a failure goes back to the implementer with the test output;
   - tasks reach `done`; the next task starts without a human.
3. Every decision above appears on the task/epic activity or the Conductor
   page with its reason. Nothing reports "dispatched"/"online" unless it is.
4. Nothing is ever pushed to any branch other than the repo's base branch
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

## 4. Design

Seven small components. Each is independently testable; none adds a new
subsystem.

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

- `PlanningTurn.status`: `queued` at creation → `delivered` when a daemon
  accepts the frame → `completed` when the Conductor's turn finishes;
  `undelivered` (with reason) if the outbox expires it. UI shows these words.
- A runtime row reads `online` only while the WS hub holds a live
  registration for it; otherwise `offline` (derived at read time from the hub,
  not a stored flag).
- Fix the planning card's "undefined task(s)" text.

### C5 — Merge into the repo's base branch (B3)

- `IntegrateSpec.target_branch` default becomes `""` meaning "the task's repo
  `default_branch`" (primary repo when the task names none). The system YAML
  drops the literal `main`.
- Resolved target is written on the `integration_requested` driver decision
  so the activity says "merging AP-123 into main-rsi".
- Daemon refuses an integrate frame whose target is empty (no silent `main`
  fallback in `core.py`).

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

### C7 — Epic intake: humans steer epics, the Conductor breaks them down

- Planning facts gain **"Epics to break down"**: epics in a managed project
  whose status is `in_progress` and that have **no open tasks** (none, or all
  done — a human re-activating a finished epic with new scope in its
  description gets a fresh breakdown).
- Planning prompt (config, `templates/conductor/planning_turn.md`) gains a
  step: for each such epic, create 3–8 tasks under it (`create_task` with
  `epic_id`, DoD with ≥1 product-level check, priority), link order with
  `add_dependency` where one must precede another, then comment on the epic
  with the breakdown rationale.
- Epic → `done` when all its tasks are done (deterministic, in the driver's
  done-handler), with an epic comment listing what shipped. Epics in
  `backlog` are never touched — that is the human's parking lot.
- New work also enters from agents: implementer/reviewer prompts (config)
  allow `create_task` into **backlog** for discovered follow-ups, linked
  `relates_to` the source task. The planning turn already promotes backlog.

### Transparency (cross-cutting)

Every loop action leaves a line a non-engineer can read, on the task or epic:
dispatched (C1), planning decisions (existing), breakdown (C7), hand-off /
bounce / hand-back (existing), merge target (C5), verification verdict (C6),
done. The Conductor page shows turn delivery states (C4).

## 5. Configuration for the proving run (no code)

- Conductor: claude runtime, `claude-opus-5-5` (done 2026-09-25).
- Conductor-managed agents on Agentira Platform: implementer-1 (Opus 5.5),
  implementer-2, senior-reviewer, reviewer, Documentation Expert. Local-model
  agents (qwen/openclaw) not conductor-enabled for v1.
- Repo `agentira`: remote `gitmaster3000/agentira-oss`, `default_branch
  main-rsi` (done). Pushes use the daemon machine's git login.
- Project: `workflow_enabled` on, `verify_cmd = scripts/verify.sh`.
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

- C1: agent with a READY run on an assigned todo task is picked; manual
  (non-managed) agent is not auto-started.
- C2: two orgs each with a Conductor; planning turn for org B's project goes
  to org B's Conductor; config read per org.
- C3: preflight adds membership once; removed membership → skip with reason.
- C4: planning turn state transitions on ack / outbox expiry; runtime online
  only with live hub registration.
- C5: target resolves to repo `default_branch`; empty target refused by daemon.
- C6 (daemon, pytest with temp git repos): pass → pushed; fail → not pushed,
  log tail returned; timeout → not pushed. Backend: failing verify → hand-back
  with log tail; missing verify_cmd → refused.
- C7: epic with no open tasks appears in planning facts; epic done when all
  tasks done.
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
