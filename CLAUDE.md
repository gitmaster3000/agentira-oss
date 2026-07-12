# Agentira / Flowty

## Communication Style
- Maximize token efficiency. Be brief, direct, no filler.
- Lead with action, not explanation.
- Skip preambles, recaps, and "let me" phrases.

## Code Style
- Minimal changes. No unnecessary refactors, comments, or abstractions.
- Test after changes: `cd frontend && npx vite build` for UI, `pytest backend/tests/` for backend.
- Follow existing patterns in the codebase.
- **Think before writing code.** Read the surrounding module, name the contract you're targeting, list assumptions. Don't start typing until the shape is clear.
- **Modular by default. Classes only when polymorphism or state make them earn their place.** Functions for everything else.
- **Maintain docs as code changes.** When you change behavior, update `/docs/`, the relevant ADR, or the runbook in the same PR. A behavior change without a doc update is half-shipped.

## Testing
- **TDD.** New feature or bug fix → write the failing test first, watch it fail for the right reason, then make it pass. A behavior change without a test is unfinished.
- **Tests run on Postgres, never SQLite.** Prod is Postgres, so tests are: `backend/tests/conftest.py` spins ONE ephemeral `testcontainers` Postgres for the session. Each test gets a fresh schema + seeded defaults + a default org with the org-context pinned. (Needs Docker running.)
- **Use the shared fixtures — don't build your own DB.** Depend on `pg` (fresh schema, seeded roles/statuses, a `TestOrg`, org context pinned; exposes `.org_id` / `.SessionLocal`) or `seed_admin` (returns `(admin_id, bearer_token)`). For REST tests, make a `TestClient(app)` and set `Authorization: Bearer <token>` — see `test_repo_tokens.py::client`.
- **Never** `create_engine("sqlite://…")`, build a private `sessionmaker`, use `StaticPool`, or `patch(...SessionLocal...)`. The real `SessionLocal` is a `RoutingSession` that reads the module-level `backend.db.engine` / `app_engine` at call time; conftest points those at the container, so the real session + its org-stamping/RLS event hooks route at the test DB automatically.
- **Org context is already set**, so new rows get `org_id` stamped for you — insert profiles/projects without spelling it out. Use `privileged()` to bypass org scoping for cross-org setup/asserts.
- **RBAC shape:** a Profile has a stored `account_type` (`human` / `agentira_agent` / `external_agent`) AND a `roles` M2M (`admin` / `member` / `viewer`). Build with `roles=[role_obj]`, never `role_id=`. There is no `bot` role.
- Run: `python -m pytest backend/tests/ -q` from the repo root (or a single file while iterating). Don't weaken an assertion to make a test pass — fix the code.

## Data Access
- **No direct DB calls in services.** `services.py` / `forge/services.py` / `forge/conductor.py` / any orchestration module must NOT use `db.query(...)`, `db.add(...)`, `db.commit(...)` inline. Every read or write goes through a per-domain data-access function (e.g. `backend/forge/repos/runs.py`, `tasks_repo.py`). Services compose; repos own the SQL.
- Why: inline `db.query` leaks ORM internals into business logic, hides N+1 traps, makes the layer untestable without a real DB, and quietly breaks when the schema moves. The repo layer is where transactions, eager-loads, and dialect quirks live.
- Existing direct-DB code is legacy. **New code uses repos. When you touch legacy code, migrate the queries you touched** (not the whole file — surgical migration).
- Repo functions take a session (`db`) or open their own via `SessionLocal()` — never both shapes in one repo. Pick one per module and stay consistent.

## Architecture
- Single DB, modular code boundaries (`backend/forge/` is self-contained).
- Real FKs between modules, no string workarounds.
- Profile stays Profile. Agent = runtime executor. Persona = future role template concept.
- Push+poll hybrid for notifications (ADR-007).
- New features go in their own `backend/<domain>.py` (or `backend/forge/<domain>.py`), not appended to `services.py`. Functions, not class hierarchies, unless there's a real polymorphism need. See `backend/attachments.py`, `backend/forge/turns.py`, `backend/forge/live_inflight.py`.
- **Adding a whole new domain? Read `docs/adding-a-feature.md` first.** It walks the gateway → handler → repo → adapter layering end-to-end, using the deploy feature as the worked reference (where the session/commit lives, when a class is warranted, when an adapter is warranted).
- **Prompts are configuration, not code.** Agent system prompts live on `Profile.system_prompt` (edited in Agent Settings UI). Task content lives on `Task.description` (edited in Task UI). Don't hardcode prompt text in dispatch code, and never re-apply a code constant on top of a user-edited row (set-if-empty seeds are the only acceptable shape).

## Plain language for users (product-wide)
- Audience is founders, software houses, solo entrepreneurs, and small teams chasing throughput — **not git or infra experts**. Everything user-facing (UI labels, settings, run badges, warnings, plan/explanation text) stays in plain language by default.
- Technical internals (branch names, base points, git mechanics, daemon details) hide behind an optional **"Advanced / technical" reveal** — present for those who want it, never in the default view.
- This is a standing rule for every feature, not a one-off. A non-engineer product owner must see the same honest status an engineer does, in words they understand.

## Products (Flowty umbrella)
- **Flowty Studio** = existing Agentira workspace/tasks (routes: `/`)
- **Flowty Forge** = agent orchestration (routes: `/forge/*`)
- Google-style app switcher between products.
