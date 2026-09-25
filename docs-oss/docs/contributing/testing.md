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

When an approved task is merged, the daemon merges it in a scratch copy, runs the project's **verify command** there, and pushes only if it exits 0. For Agentira itself that command is:

```bash
scripts/verify.sh
```

It installs the locked backend dependencies into a cached virtualenv, runs the backend suite, then the frontend tests and build. The daemon machine needs `uv`, Node.js and Docker.

If it fails, nothing is pushed and the task goes back to the implementer with the output. What happens on failure is set in `templates/workflow/default.yaml` (`integrate.verify`, `integrate.on_failure`); the command itself is the project setting "Command that proves the project works".
