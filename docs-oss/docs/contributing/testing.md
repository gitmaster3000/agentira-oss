---
id: testing
title: Testing
sidebar_label: Testing
---

# Testing

## Test-driven, not test-after

New feature or bug fix: write the failing test first, watch it fail **for the right reason**, then make it pass.

A test that passes before your change tests nothing. A behaviour change without a test is unfinished.

## Postgres, never SQLite

`backend/tests/conftest.py` starts one ephemeral Postgres container for the session and gives each test a fresh schema.

Docker must be running.

Production is Postgres, so tests are Postgres. Engine differences — dialect quirks, constraint timing, JSON handling — otherwise pass in tests and fail in production.

## Use the shared fixtures

| Fixture | Provides |
|---|---|
| `pg` | Fresh schema, seeded roles and statuses, a test organisation with context pinned. Exposes `.org_id` and `.SessionLocal`. |
| `seed_admin` | Returns `(admin_id, bearer_token)` |

For REST tests, construct a `TestClient(app)` and set `Authorization: Bearer <token>`. `test_repo_tokens.py::client` is the reference.

### Never build your own database

Do not:

- `create_engine("sqlite://…")`
- Construct a private `sessionmaker`
- Use `StaticPool`
- Patch `SessionLocal`

The real `SessionLocal` is a routing session that reads the module-level engine at call time. The test configuration points that engine at the container, so the real session and its organisation-stamping and row-level-security hooks route to the test database automatically.

Bypassing it produces tests that pass while testing the wrong thing.

## Organisation context

Context is already set, so new rows are stamped for you. Insert profiles and projects without spelling out the organisation.

Use `privileged()` to bypass organisation scoping for cross-organisation setup or assertions.

## Running tests

```bash
# Full backend suite
python -m pytest backend/tests/ -q

# One file while iterating
python -m pytest backend/tests/test_gates.py -q

# CLI suite
python -m pytest agentira-cli/tests/ -q

# Frontend build
cd frontend && npm ci && npx vite build
```

`tests/` at the repository root is legacy and folds into `backend/tests/` over time.

## End-to-end browser tests

Real-browser tests (Playwright, in `frontend/e2e/`) sign in through the login page and click through the main screens: workspace, projects, tasks (create, edit, comment, move), epics, roadmap, the Build area, notifications, the dark/light toggle, and the phone-width layout. They run on every pull request that touches `frontend/` or `backend/`.

They need a running copy of Agentira with a known test user. The compose file `docker-compose.e2e.yml` builds one that is isolated from your dev stack: its own project name, its own throwaway database, and one published port (`3211` by default).

```bash
# 1. Start an isolated stack (builds from your working tree)
docker compose -p ap-e2e -f docker-compose.e2e.yml up -d --build --wait

# 2. Create the test user (e2e-admin, throwaway password)
docker compose -p ap-e2e -f docker-compose.e2e.yml exec -T backend python scripts/seed_e2e_user.py

# 3. Run the tests (first time only: npx playwright install chromium)
cd frontend && npm ci
E2E_BASE_URL=http://localhost:3211 npm run e2e

# 4. Tear down, including the database
docker compose -p ap-e2e -f docker-compose.e2e.yml down -v
```

`E2E_BASE_URL` defaults to `http://localhost:3111`. Change the published port with `E2E_WEB_PORT`. Open the last report with `npx playwright show-report`; a trace is recorded for any test that needed a retry.

Two Playwright projects run every spec except `mobile.spec.js`: `desktop` (1440×900) and `mobile` (375×812). `mobile.spec.js` runs on `mobile` only and checks the board and task page do not scroll sideways.

Writing specs:

- Each spec creates its own data with a unique name (`uniqueName()` in `e2e/helpers.js`), so specs can run in parallel and in any order.
- Find elements the way a person would: `getByRole`, `getByLabel`, `getByText`. Add a `data-testid` only where there is no accessible handle, and prefer giving the element a proper name (as the notifications bell now has).
- The global setup signs in once and shares the session; the test user is created by `backend/e2e_seed.py` through the normal invite path, in its own organisation.

### How CI runs it

`.github/workflows/e2e.yml` runs on pull requests to `main` and on manual dispatch. It does the same four steps as above on a GitHub-hosted runner, with the compose project named after the run so concurrent runs never share anything. It uses no secrets, so pull requests from forks run too.

If a run fails, the workflow uploads `playwright-report/` and `test-results/` (screenshots, traces) as the `playwright-report` artifact and prints the stack logs. Open a trace with `npx playwright show-trace <trace.zip>`.

The stack is compose with the production web image rather than `vite dev`/`vite preview` on the runner. Both Node servers close idle connections after five seconds, which makes Chrome intermittently fail a request ("Failed to fetch") and flakes the suite; nginx does not.

## Do not weaken assertions

If a test fails, fix the code. Loosening an assertion to get a green run converts a caught bug into a shipped one.

If an assertion is genuinely wrong, say so explicitly in the pull request and explain why. Do not quietly relax it.

## What to test

**Every behaviour you add.** The test should fail without your change.

**Every behaviour you preserve.** Regression-pin anything a future change might plausibly break.

**The unknown path**, for anything touching evidence. An evidence provider that answers `unknown` must block. That path matters more than the happy path, because failing closed is the whole design.

**Permission boundaries.** A tool or endpoint reachable by the wrong role is a real defect.

## Continuous integration

Required before merge:

- Unit tests
- Compose configuration validation
- An integration smoke test that boots the backend and MCP

Comment `/integration-test` on a pull request to run the full suite with the CLI installed.

## What must pass before Agentira merges

Nothing is merged without a pull request. When an approved task is merged, the daemon checks out the pull request's merge result in a scratch copy, runs the project's **verify command** there, and only if it exits 0 asks GitHub to merge the pull request (the daemon uses your `gh` login and never pushes to the base branch itself). For Agentira itself that command is:

```bash
scripts/verify.sh
```

It installs the locked backend dependencies into a cached virtualenv, runs the backend suite, then the frontend tests and build. The daemon machine needs `uv`, Node.js and Docker.

If it fails, or the pull request conflicts or is not mergeable, nothing is merged and the task goes back to the implementer with the output. Policy is set in `templates/workflow/default.yaml`: `integrate.via: pull_request`, `integrate.merge_method` (`merge`, `squash` or `rebase`), `integrate.verify`, `integrate.on_failure`; the command itself is the project setting "Command that proves the project works".
