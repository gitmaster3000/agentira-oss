# Agentira Self-Sufficiency — Findings & Plan

> Author: Claude (planning pass, 2026-06-10). Goal #1: make Agentira a
> self-sufficient project that works on itself, human-in-the-loop, with daily
> reports. This doc is findings + plan; nothing here is executed without your ok.

## What you asked for

A board-driven SDLC where the **Conductor plans/assigns/dispatches** and
**column-bound agents** do role-specific work, reassigned by state:

```
backlog → todo → in_progress → review → (docs) → done
            │         │            │         │
          PLAN    IMPLEMENT     REVIEW     DOCUMENT
        (planner) (implementer) (a DIFFERENT  (doc agent,
                                 agent)        after review passes)
```

Plus: clean up the messy backlog/epics, set up the team, and have the team
build a real product (fitness app) in the Smoke project as the dogfood proof.

Your four goals, in priority order: **(1) self-sufficient (now)** · (2) first-user
onboarding (daemon install + Railway signup) · (3) polish/robustness · (4)
feature deployment to QA/Railway.

## Findings

### A. What already works (verified in code + live this session)
- **Run loop, end-to-end (git):** clone local/remote → per-task worktree →
  agent commits on a branch → artifact → `finish_run(succeeded)`. Proven live
  (run `3ab72872d0fe`: implementer-1 created+committed `backend/health.py`).
- **Conductor:** planning turn (LLM assigns the backlog), deterministic tick
  (dispatches assigned work, token-free), daily report — all scheduled,
  master-gated by `conductor_active`. **Intelligent dispatch shipped this
  session** (assigned-only, priority-ordered, skill-match via agent specialty
  facts — AP-203).
- **Gate engine** (`backend/gates.py`): validates all four transitions with
  evidence — `has_dod`, `has_assignee`, `dod_all_checked`, `has_branch_or_pr`,
  `pr_url_set`. Opt-in per project via `gates_enabled`.
- **Foundations:** workspace kinds git/sandbox (AP-197/202), concurrency now
  env-configurable (AP-201, was hard-capped at 3), prompts-as-config, run state
  machine + reconciler.

### B. The core gap — why Agentira is NOT self-sufficient yet
**There is no workflow engine that DRIVES the board.** Concretely:
- The Conductor assigns a task **once** (at `todo`) to **one** agent and
  dispatches it.
- The agent works, calls `finish_run(succeeded)` — and the task **stays in
  `in_progress`**. Nothing advances it to `review`, nothing reassigns it to a
  **different** reviewer, nothing spawns docs, nothing merges the branch.
- The gate engine only **blocks bad manual moves**; it never **moves** a task
  or **reassigns** an agent. It's a validator, not a driver.
- Agent branches commit into the shared clone but **never merge to `main`**, so
  a multi-task product never coheres.

So your plan→implement→review-by-a-different-agent→document pipeline is
**designed (epic `38ecf74dba7c`) but not built as a runtime loop.** Building
that loop *is* goal #1.

### C. The backlog mess (19 epics, ~190 tasks) — heavy overlap + dead concepts
- **Conductor: two epics** — `d6515265a48e` "Conductor — LLM orchestrator" and
  `91aa805d3c8b` "Step 6 — Conductor" are duplicates.
- **Workflow/gates: one new epic supersedes five old "Step N" epics** — the
  unified `38ecf74dba7c` absorbs Steps 2/3/4/5/7 (`a0916498255f`,
  `1afc0dfad1cd`, `aeb17a8835af`, `5dbbdb31e6ab`, `9ab3836dd2c6`).
- **Run/chat battles: three epics** — `1deb05818c55` (Runs & Chats Reconciliation,
  11), `9968d271331e` (Conversations/Turns/Runs ADR-009, 12), `a93dc4064579`
  (Runtime Adapter, 3). Largely overtaken by recent work; need a done/superseded
  sweep, not more building.
- **Mostly-done foundations → polish (goal #3):** `ae5632316bc5` Run Context
  (20), `0b30b6562d6b` UI overhaul (29), `c10ea54a1209` Notifications/Autonomy (5).
- **Maps to goal #2:** `abcdc1abb6b8` Pre-Launch Sprint (7) + `e776d81d315d`
  First team onboarding (0).
- **`ec21a625ab44` "I'd actually use this" (0 tasks)** is literally the
  self-sufficiency bar — empty; should become the home of the Phase-1 build.

## Plan

### Phase 0 — Backlog cleanup (propose → you approve → I execute via MCP)
Consolidate ~19 epics → **6 focused epics** aligned to your goals; **tag**
(not delete) superseded tasks `superseded`/`archived` for your review:
1. **Self-Sufficiency: Workflow Engine** (#1) — absorbs `38ecf…`, the five
   Step-N epics, both Conductor epics, and the quality-bar epic.
2. **Run/Chat closeout** — verify done, archive the rest of the three epics.
3. **Onboarding & Railway** (#2) — Pre-Launch Sprint + First-team onboarding.
4. **Polish & Robustness** (#3) — UI overhaul + Notifications/Autonomy + Run Context tail.
5. **Deployment to QA/Railway** (#4).
6. **Platform plumbing** (keep as-is).

### Phase 1 — Build the Workflow Engine (THE #1 build; extends Conductor + gates)
Reuse the gate engine + Conductor; add the missing **driver**:
1. **Column→role roster** per project (config/template): `todo`→Planner,
   `in_progress`→Implementer, `review`→Reviewer, `done`. Default roster +
   override.
2. **Auto-advance on success**: when a run finishes `succeeded` and the
   column's exit-gate passes, move the task to the next column (deterministic,
   token-free; hooks `finish_run`).
3. **Reassign + re-dispatch on column entry**: assign the next column's
   role-agent (enforce **reviewer ≠ implementer**) and dispatch it with the
   column-prompt as preamble.
4. **Reviewer merges to main**: on review pass, the Reviewer merges the branch
   into `main` in the shared clone and pushes to origin → the product coheres.
5. **Docs after review**: spawn a documentation step once review succeeds.
6. **Daily report**: confirm `run_daily_report` emits the executive HTML for the
   human-in-the-loop.

Bootstrapping note: **Claude builds the engine; Agentira then runs on it.** The
engine is the prerequisite for self-sufficiency, so it can't dogfood its own
construction.

### Phase 2 — Team + first product (dogfood)
Stand up your exact roster and let the engine run the fitness app in Smoke:
| Agent | Model | Role |
|---|---|---|
| implementer-1 | claude-opus-4-8 | Senior architect / full-stack |
| implementer-2 | claude-opus-4-7 | Senior backend |
| frontend | claude-opus-4-7 | Senior frontend |
| documentation | claude-opus-4-7 | Docs (after review) |
| junior full-stack | qwen-3.6 (openclaw) | Junior |
| junior 2 | qwen-3.6 (openclaw) | Junior |
Conductor plans/assigns; Reviewer (a senior, ≠ implementer) reviews + merges.

## Open decisions for you
1. Approve the **epic-consolidation map** (Phase 0) before I tag/restructure?
2. Phase 1: build the workflow engine as **one new epic with discrete tasks**
   (I create them on the board), correct?
3. Reviewer policy: reviewer must be a **different agent** than the implementer —
   confirm a senior reviews (e.g. architect reviews backend, backend reviews
   frontend), juniors never review.
