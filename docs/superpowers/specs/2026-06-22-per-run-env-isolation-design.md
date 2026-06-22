# Per-Run Environment Isolation — Design Spec

**Date:** 2026-06-22
**Status:** Draft (pending implementation plan)
**Maps to:** ADR 010 (to be written on implementation), epic AP-TBD
**Repos touched:** `agentira` (backend), `agentira-cli` (daemon), `agentira-frontend` (settings UI)

---

## 1. Context & Problem

Agentira isolates a run's **workspace** (a git worktree per task, plus a locked-down
agent home) but does **not** isolate the **runtime environment** the agent's commands
execute against. The moment an agent runs `pytest`, `npm test`, a migration, or boots a
dev server, those commands hit **shared, long-lived, mutable resources** the daemon
inherited from the host:

- the shared docker-compose dev stack (one Postgres, one backend, etc.),
- fixed host ports (5432, 8111, 3111),
- the host environment — `_build_env` (`agentira-cli/agentira_cli/daemon/executor.py:511`)
  passes **all** of `os.environ` (minus the daemon API key) into every agent subprocess,
  so `AGENTIRA_DB_URL` and friends leak in wholesale.

**Source is forked per task; everything the source talks to is a singleton.** Any command
that mutates a shared resource is therefore a cross-agent race. The recurring "org_id"
test failure is one instance; the same disease produces "port already in use," migrations
clobbering each other, one agent's test data poisoning another's assertions, and corrupted
shared docker volumes. **This will recur in every service-backed project**, because the
isolation boundary stops at the filesystem.

### Goal

Extend Agentira's isolation philosophy one layer down: the worktree forks the *source*;
a new primitive forks the *environment*. Each run gets an **ephemeral, namespaced,
disposable** environment, and the agent's commands can only reach **its own** services.
Agents must never touch the developer's long-lived dev stack — that stack is for the human.

### Non-goals (explicit YAGNI)

- No persistent per-agent containers.
- No daemon-in-a-container.
- No VM / microVM isolation.

The unit of isolation is the **run** (consistent with the "one sticky run per task" model);
cost scales with *concurrent active runs*, not with number of agents.

---

## 2. Core Design — one primitive, three presets

Rather than three bespoke subsystems, all isolation strategies are **presets over a single
per-run environment hook**:

> On run start, after the worktree is materialized and before the agent subprocess is
> spawned, the daemon runs an optional **`env_setup`** step. `env_setup` provisions an
> isolated environment and emits connection variables as `KEY=VALUE` lines on stdout.
> The daemon captures those and merges them into `env_extra` (the existing injection
> channel). On run finish — success, failure, or cancel — the daemon runs **`env_teardown`**.
> The environment lives for the whole run (sticky, per task), shared across turns.

This is not a shortcut: it is the honest shape. "Modes" are configuration over one
mechanism, and each mode below is fully specified and fully implemented.

### The three modes

| Mode | `env_setup` does | Agent receives | Teardown | Cost |
|---|---|---|---|---|
| **Hermetic** | nothing; daemon *strips* shared service URLs from the inherited env | clean env — the project's own suite falls back to its in-memory/file DB | none | zero |
| **Per-run DB** | built-in: create a throwaway database `run_<run_id>` in the project's configured DB server, run schema bootstrap, emit `AGENTIRA_DB_URL=<…>/run_<run_id>` | its own isolated database in the existing Postgres server | `DROP DATABASE run_<run_id>` | ~nil (one PG process) |
| **Per-run compose** | run the project-declared up command (default template: `docker compose -p run_<run_id> up -d --wait`) with ephemeral host ports, then emit service URLs | its own full multi-service stack | project-declared down command (default: `docker compose -p run_<run_id> down -v`) | one stack per *active* run |

### Auto resolution (the default mode)

A project starts at `env_isolation = auto`. At **dispatch time** (backend), `auto` resolves:

1. Repo declares services — a `docker-compose*.yml` exists at repo root **or** the project
   has explicit declared services → **Per-run DB**.
2. Otherwise → **Hermetic**.

`per_run_compose` is **never** chosen by auto; it is explicit opt-in (it is the only mode
that brings up arbitrary containers and binds host ports, so it should be a deliberate
choice). Auto therefore yields "cheapest that works + maximum isolation" with no surprises.

---

## 3. Configuration model

### Project-level field (`agentira` backend, `backend/models.py` → `Project`)

```
env_isolation        VARCHAR(20)   -- 'auto' (default) | 'hermetic' | 'per_run_db' | 'per_run_compose'
env_setup_cmd        TEXT NULL     -- override for per_run_compose up (and custom setups)
env_teardown_cmd     TEXT NULL     -- override for teardown
env_db_admin_url     VARCHAR(500) NULL  -- for per_run_db: admin DSN to CREATE/DROP databases
                                        -- (defaults to the project's configured app DB server)
```

- Sits beside `workspace_kind` and `sandbox_mode` (same per-project containment family).
- Added via the idempotent column-add migration pattern in `backend/db.py:run_migrations`
  (`_ensure_column`), exactly like `workspace_kind` (db.py:640) and `sandbox_mode`
  (db.py:601/635).
- Built-in default commands (the Per-run DB SQL, the compose up/down templates) live as
  **daemon-side constants**, not in the DB — only *overrides* are stored. This keeps
  project rows lean and the defaults versioned with the daemon.

### Resolved mode on the dispatch frame

`backend/forge/services.py:dispatch_trigger` already packs `workspace_kind`, `sandbox_mode`,
etc. onto the frame and merges `env_extra` (services.py:2511-2567). Add:

- `env_isolation` — the **resolved** mode (auto already collapsed to a concrete value, so
  the daemon never re-implements detection).
- `env_setup_cmd` / `env_teardown_cmd` — resolved (override or built-in template, with
  `<run_id>` / `<db_admin_url>` placeholders pre-substituted where known).

Resolution of `auto` happens in the backend at dispatch (it has the project row + repo
metadata). The daemon receives a concrete instruction and executes it — single
responsibility, no duplicated detection logic.

---

## 4. Daemon implementation (`agentira-cli/agentira_cli/daemon`)

All work lands in a new focused module **`env_isolation.py`** (per CLAUDE.md: new concern →
its own module, functions not classes). `core.py:_execute` calls into it at two points.

### 4.1 Provision (in `_execute`, after materialize ~core.py:744, before spawn ~core.py:902)

```
provisioned_env, teardown_ctx = await provision_env(
    mode=frame["env_isolation"],
    run_id=run_id,
    cwd=cwd_path,
    setup_cmd=frame.get("env_setup_cmd"),
    db_admin_url=frame.get("env_db_admin_url"),
)
env_extra.update(provisioned_env)   # injected via existing _build_env merge
```

- **Hermetic:** returns no env to add; instead returns a `strip` set
  (`AGENTIRA_DB_URL`, `AGENTIRA_APP_DB_URL`, plus any project-declared service vars) that
  `_build_env` removes from the inherited environment. Implement by extending `_build_env`'s
  `_BLOCKED` set with a per-run strip list passed through (executor.py:511).
- **Per-run DB:** connect to `db_admin_url` (admin/superuser DSN), `CREATE DATABASE
  run_<run_id>`, run the app's schema bootstrap against it (reuse `backend.db.init_db`
  semantics via a small subprocess/SQL path so the daemon stays decoupled from backend
  imports — see §4.3), emit `AGENTIRA_DB_URL` pointing at the new DB. `run_id` is already
  unique and present in `_execute`.
- **Per-run compose:** run `setup_cmd` (built-in template or override) with
  `COMPOSE_PROJECT_NAME=run_<run_id>` and ephemeral host ports; parse `KEY=VALUE` lines the
  command emits on stdout into the injected env. `--wait` ensures services are healthy
  before the agent starts.

`provision_env` returns a **`teardown_ctx`** capturing exactly what to undo (db name + admin
url, or compose project name + down cmd, or nothing).

### 4.2 Teardown (in `_execute`, run-finish path alongside `_cleanup_worktree` ~core.py:1008-1127)

```
finally:
    await teardown_env(teardown_ctx)   # idempotent; never raises into the run path
```

- Runs on **every** exit path (success, failure, cancel, timeout) — same lifecycle hook as
  worktree cleanup, so a killed run cannot leak a DB or a compose stack.
- **Idempotent and crash-safe:** teardown context is also persisted to the on-disk inflight
  registry (`~/.agentira/inflight/<scope>.json`, already used to reap orphan processes on
  daemon restart). On daemon startup, `reap_orphans` additionally drops orphaned `run_<id>`
  databases / `compose -p run_<id> down` for any inflight record whose process is gone.
  This guarantees "disposable" holds even across daemon crashes.

### 4.3 Decoupling note (no shortcut, but no tangle)

The daemon must not import the backend package. For Per-run DB schema bootstrap, two
acceptable concrete options (decided in the implementation plan, not deferred):

- **(a)** the daemon invokes a tiny backend-provided entrypoint (`python -m backend.db
  --bootstrap --url <dsn>`) — reuses the real schema/migrations, zero drift.
- **(b)** the project declares its own bootstrap command (`env_setup_cmd`) and the built-in
  is only the `CREATE DATABASE` + handing the DSN to that command.

Recommendation: **(a)** for the agentira repo itself (exact schema parity) and **(b)** as the
generic path for arbitrary customer projects. Both are real, neither is a stub.

---

## 5. Frontend (`agentira-frontend`)

One control in **Project Settings**, plain-language per CLAUDE.md (audience: non-infra
founders), with technical names behind the existing "Advanced / technical" reveal.

| Plain label | Mode | Help text |
|---|---|---|
| "Automatic (recommended)" | `auto` | "Agentira picks the safest, cheapest isolation for this project." |
| "No shared services" | `hermetic` | "Runs use a clean, empty environment. Best when tests don't need a live database." |
| "Isolated database per run" | `per_run_db` | "Each run gets its own throwaway database. Agents never share data." |
| "Isolated full stack per run" | `per_run_compose` | "Each run gets its own full set of services. Heaviest, strongest isolation." |

Wire to the project update API (same surface that already persists `sandbox_mode` /
`workspace_kind`).

---

## 6. Failure handling (explicit — "working stuff")

| Failure | Behavior |
|---|---|
| `env_setup` non-zero exit / timeout | Run is marked failed with a clear `materialize_reason`-style diagnostic ("environment setup failed: …"); agent is **not** spawned (a run without its DB would silently fall back to shared infra — exactly what we're preventing). Partial provision is torn down. |
| `env_setup` emits malformed env lines | Provision fails closed (same as above); we never inject a half-populated env. |
| `env_teardown` fails | Logged; recorded in inflight registry for reap on next startup. Never blocks or fails the run's reported outcome. |
| Daemon crash mid-run | On restart, `reap_orphans` drops the orphaned `run_<id>` DB / compose project from the persisted teardown context. |
| Per-run DB: admin URL unreachable | Provision fails closed with an actionable diagnostic ("could not reach database server to create the per-run database"). |
| Hermetic but suite genuinely needs a DB | Suite fails on its own missing-DB error (correct signal); project owner flips the setting to Per-run DB. Documented in the setting's help + runbook. |

---

## 7. Testing strategy (no shortcuts)

- **Mode resolution (backend, unit):** `auto` → `per_run_db` when a compose file / declared
  services present; → `hermetic` otherwise. Explicit modes pass through unchanged.
- **Provision/teardown (daemon, unit, mocked subprocess):** each mode produces the expected
  injected env + teardown context; teardown is idempotent and never raises.
- **Hermetic strip (daemon, unit):** inherited `AGENTIRA_DB_URL` is absent from the built
  subprocess env in hermetic mode; present (pointing at `run_<id>`) in per-run-db mode.
- **Per-run DB integration:** against a real local Postgres — provision creates a reachable
  `run_<id>` DB with the full schema, teardown drops it, two concurrent runs get distinct
  DBs and cannot see each other's rows (this is the regression test for the org_id /
  shared-state class of bug).
- **Orphan reap:** simulate an inflight record with a dead PID + a leftover `run_<id>` DB;
  startup reap drops it.
- **Frontend:** the setting persists and round-trips via the project update API.

---

## 8. Relationship to the org_id symptom

Under `auto`, the agentira repo (compose present) resolves to **Per-run DB**: every run gets
its own database, so concurrent agents can never collide on org rows or any other shared
state. The standalone one-line seed fix (`_ensure_system_org` inside `_seed_defaults`) is
still worth landing for the in-memory SQLite suite, but it stops being an *environment*
problem. The structural cause — agents sharing the dev stack — is removed for **every**
project, which is the "solve it once and for all" outcome.

---

## 9. Implementation surface summary

| Repo | Files | Change |
|---|---|---|
| `agentira` | `backend/models.py` | add `env_isolation` + override columns to `Project` |
| `agentira` | `backend/db.py:run_migrations` | idempotent column-add (mirror `workspace_kind`) |
| `agentira` | `backend/forge/services.py:dispatch_trigger` | resolve `auto`; pack mode + cmds on frame |
| `agentira` | `backend/db.py` | `--bootstrap --url` entrypoint for per-run-db schema (option a) |
| `agentira-cli` | `daemon/env_isolation.py` (new) | `provision_env` / `teardown_env` / strip list |
| `agentira-cli` | `daemon/core.py:_execute` | call provision (post-materialize) + teardown (finish path) |
| `agentira-cli` | `daemon/executor.py:_build_env` | accept + apply per-run strip set |
| `agentira-cli` | `daemon/inflight.py` | persist teardown ctx; reap orphan DBs/stacks on startup |
| `agentira-frontend` | Project Settings | mode select (plain labels + Advanced reveal) |

---

## 10. Open decisions deferred to the implementation plan

- Per-run-DB schema bootstrap: confirm option (a) entrypoint shape vs (b) project command.
- Compose ephemeral-port discovery: rely on the project's emitted `KEY=VALUE` lines vs
  Agentira inspecting `docker compose port`. Lean: project emits, Agentira stays generic.
- Whether `auto`'s "declared services" signal includes anything beyond a root
  `docker-compose*.yml` (e.g. a `[tool.agentira.services]` block).
