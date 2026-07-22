# Conductor turns v2 — isolated, per-project, auditable

Status: implemented 2026-07-22 (branch `feat/conductor-turn-scopes`).

## Why

The Conductor previously ran **one aggregate LLM turn** for planning and for
the progress watchdog, dispatched into the single conversation scope
`chat:default`, shared across every project the Conductor manages. That had
three problems:

1. **Unbounded growth.** Every planning/progress turn, forever, appended to
   the same conversation. `assemble_context` rebuilds that history on every
   dispatch — this was the root cause of a Postgres DiskFull incident
   (large `AgentMessage` rows over a long-lived scope).
2. **Cross-project pollution.** One composed prompt mixed every managed
   project's task titles/descriptions together. Beyond noise, this is a
   prompt-injection surface: a hostile task description in project A could
   attempt to steer a decision that touches project B.
3. **No transparency for two of the four dispatch paths.** `run_daily_report`
   and `run_progress_check_turn` never wrote a `PlanningTurn` audit row —
   only `run_planning_turn` did.

## What changed

Every Conductor judgment turn — planning, progress check, sprint review, and
the daily report — now:

- Runs **once per conductor-managed project** (planning/progress/sprint
  review) or globally with its own dedicated scope (daily report, which is
  a cross-project human digest by design).
- Gets its **own conversation scope**, `turn:{planning_turn_id}` — never
  `chat:default`. Each turn is a short-lived, self-contained conversation;
  nothing accumulates across turns.
- Produces a durable `PlanningTurn` row (`backend/forge/repos/planning_turns.py`)
  **before** dispatch, with `trigger` set to `"cron"` (planning),
  `"progress_check"`, `"sprint_review"`, or `"daily_report"`, `status`
  starting at `"dispatched"` and flipped to `"error"` if the send fails, and
  `facts_snapshot` including `project_id`/`project_name` for planning and
  sprint-review turns.
- Has an **injection guard** (`templates/conductor/turn_guard.md`) prepended
  to the composed prompt — same authoritative-rules pattern as
  `templates/epic_planning/system_prompt.md`: task content is DATA (fenced
  in ``` blocks```), the turn is scoped to one named project, and only the
  MCP tools named in the turn's own instructions may be used.

### Managed projects

"Managed" = the set of `project_id`s with at least one
`Profile.conductor_enabled=True` agent whose `default_project_id` is set to
that project (`conductor._managed_projects`). Planning, progress-check, and
sprint-review each loop over this set and dispatch (or skip, token-free) one
turn per project.

### Planning turn v2 (`gather_planning_facts(project_id)`)

Facts are now project-scoped: the project's conductor-enabled agents, its
UNASSIGNED todo tasks, its top 30 backlog tasks (priority-ranked, description
capped at 300 chars), and the team's free capacity
(`sum(agent.capacity - agent.in_flight)`). The prompt
(`templates/conductor/planning_turn.md`) asks the Conductor to do two things:

1. **Promote** up to `capacity` backlog tasks into `todo` — each promotion
   sets verification-shaped `dod_items` (3-6 items, at least one a
   **product-level** check a human can run against the running app, not just
   "unit tests pass"), assigns the best-fit agent, moves the task, and posts
   a one-line rationale comment (traceability).
2. **Assign** any todo task still unassigned, by specialty → priority →
   load.

### Sprint review (new)

`run_sprint_review_turn()` — daily at 07:30 UTC (`ForgeScheduler`), per
project. Facts (`gather_planning_facts`'s sibling,
`gather_sprint_review_facts(project_id)`) are the project's 24h digest
(`backend/forge/digest.py`, already project-scoped and token-free) plus a
count of workflow bounce/escalation comments in the window
(`backend/forge/repos/activities.py::count_bounce_escalation_comments`).
Skips when the digest is empty and there was no bounce/escalation activity.
The prompt (`templates/conductor/sprint_review.md`) asks the Conductor to
write a short human-readable retro, file corrective backlog tasks for any
systemic issue, and publish the review itself as a `done`, `sprint-review`
tagged task so a non-technical product owner reads it on the board.

Manual trigger: `POST /forge/conductor/sprint-review`.

### Progress check

`gather_progress_facts` gained an optional `project_id` argument — `None`
preserves the old cross-project scan (used directly by its own unit tests);
`run_progress_check_turn` always passes a concrete `project_id`, one call per
managed project, so its stalled-task facts and its turn scope never mix
projects either.

### Daily report

Stays a single, cross-project human digest by design (that's its whole
point — an executive summary of the whole workspace). It now also gets a
`turn:{id}` scope (never `chat:default`) and a `PlanningTurn` record
(`trigger="daily_report"`), for the same transparency contract as the other
turns.

## Deviations from the original spec

- **Gate-evaluation counts omitted from the sprint review.** `GateEvaluation`
  (`backend/forge/models.py`) has no timestamp column, so a cheap 24h-window
  count isn't available without a schema migration — out of scope for this
  pass. The sprint review still surfaces bounce/escalation *comments*
  (which do carry `created_at`) as the systemic-issue signal.
- **Sprint-review cadence is a fixed cron (07:30 UTC), not yet
  config-driven** like `plan_interval_minutes` — the spec allowed this
  ("daily 07:30 UTC via scheduler"); wiring it into `get_conductor_config`
  is a natural follow-up if the fixed time needs to become configurable.
- **`run_planning_turn()` / `run_progress_check_turn()` / `run_sprint_review_turn()`
  return shape changed** from a flat `{"ok": ..., ...}` / `{"skipped": ...}`
  dict to `{"projects": [...]}` (one result dict per managed project), with
  the flat `{"skipped": "..."}` shape preserved only for the turn-level
  skips that precede the per-project loop (`conductor_disabled`,
  `no_conductor`, `no_managed_projects`, `no_runtime`). Existing tests and
  callers (`backend/forge/router.py`'s `/conductor/plan` etc.) were updated;
  this is the direct, intended consequence of moving from one aggregate turn
  to N per-project turns.
- **When there are zero managed projects, no `PlanningTurn` row is written**
  for planning/progress-check/sprint-review (there is no project to scope a
  turn to). Previously a single aggregate "nothing to plan" turn was always
  recorded even with zero conductor-enabled agents; that no longer applies
  once the record is inherently per-project.

## Hardening: context assembly never crashes a turn

`backend/forge/context.py::assemble_context` now wraps the entire history
rebuild (the DB query + token-budget walk + rolling-summary lookup) in a
`try/except`. If it raises for any reason — a wedged connection, a Postgres
`OperationalError`, anything — `assemble_context` logs a warning with the
`scope_key` and returns `current` unchanged: the turn dispatches with a
fresh, history-less prompt instead of failing outright. This directly
targets the 2026-07-22 23:39 DiskFull recurrence, where a broken history
query previously had no fallback path.

See `backend/tests/test_rebuild_history.py::test_broken_history_query_degrades_to_current`
and `::test_broken_history_query_operational_error_degrades_to_current`.

## Files

- `backend/forge/conductor.py` — per-project turn loops, sprint review,
  injection-guarded prompt composition.
- `backend/forge/repos/tasks.py` — `backlog_candidates`.
- `backend/forge/repos/planning_turns.py` — `set_scope_key`, `update_status`.
- `backend/forge/repos/activities.py` — `count_bounce_escalation_comments`.
- `backend/forge/context.py` — history-rebuild hardening.
- `backend/forge/scheduler.py` — sprint-review cron (07:30 UTC).
- `backend/forge/router.py` — `POST /forge/conductor/sprint-review`.
- `templates/conductor/turn_guard.md`, `templates/conductor/planning_turn.md`
  (v2), `templates/conductor/sprint_review.md` (new).
