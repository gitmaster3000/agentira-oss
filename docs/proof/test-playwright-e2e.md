# Proof: test/playwright-e2e

Isolated stack: compose project `ap-e2e`, web on port 3211 (not 3113/8111/8000/5432). Torn down afterwards; `docker ps | grep -c ap-e2e` → 0.

## Stack up and seed (from a clean `down -v`)

```
$ docker compose -p ap-e2e -f docker-compose.e2e.yml down -v
 Container ap-e2e-backend-1 Removing 
 Container ap-e2e-backend-1 Removed 
 Container ap-e2e-postgres-1 Stopping 
 Container ap-e2e-postgres-1 Stopped 
 Container ap-e2e-postgres-1 Removing 
 Container ap-e2e-postgres-1 Removed 
 Network ap-e2e_default Removing 
 Network ap-e2e_default Removed 

$ docker compose -p ap-e2e -f docker-compose.e2e.yml up -d --build --wait
 Container ap-e2e-backend-1 Starting 
 Container ap-e2e-backend-1 Started 
 Container ap-e2e-backend-1 Waiting 
 Container ap-e2e-backend-1 Healthy 
 Container ap-e2e-frontend-1 Starting 
 Container ap-e2e-frontend-1 Started 
 Container ap-e2e-frontend-1 Waiting 
 Container ap-e2e-postgres-1 Waiting 
 Container ap-e2e-backend-1 Waiting 
 Container ap-e2e-backend-1 Healthy 
 Container ap-e2e-postgres-1 Healthy 
 Container ap-e2e-frontend-1 Healthy 

$ ... exec -T backend python scripts/seed_e2e_user.py
created: e2e-admin
SMTP not configured (SMTP_HOST unset) — skipping email to e2e-admin@example.test (Welcome to Agentira)
```

## Browser tests (CI settings: `CI=true`, 2 workers) — 3 consecutive runs, all green

```
$ cd frontend && E2E_BASE_URL=http://localhost:3211 CI=true npm run e2e

> agentira-frontend@0.1.0 e2e
> playwright test


Running 23 tests using 2 workers

  ✓   2 [desktop] › e2e/areas.spec.js:20:1 › roadmap view renders with the project tasks (1.2s)
  ✓   1 [desktop] › e2e/areas.spec.js:4:1 › epics list opens and shows a new epic (1.6s)
  ✓   4 [desktop] › e2e/areas.spec.js:37:1 › the notifications bell opens and closes (428ms)
  ✓   3 [desktop] › e2e/areas.spec.js:28:1 › the Build area renders the agents page (1.2s)
  ✓   5 [desktop] › e2e/areas.spec.js:47:1 › the theme toggle switches between dark and light and remembers it (482ms)
  ✓   6 [desktop] › e2e/auth.spec.js:7:5 › signed out › wrong password is rejected (660ms)
  ✓   7 [desktop] › e2e/auth.spec.js:16:5 › signed out › signing in lands on the workspace (618ms)
  ✓   8 [desktop] › e2e/auth.spec.js:25:5 › signed out › a private page sends you to sign in (327ms)
  ✓   9 [desktop] › e2e/auth.spec.js:32:1 › a saved session opens the workspace directly (357ms)
  ✓  10 [desktop] › e2e/project.spec.js:4:1 › create a project and see it on the board and the home page (897ms)
  ✓  11 [desktop] › e2e/task.spec.js:4:1 › create, open, edit, comment on and move a task (1.8s)
  ✓  12 [mobile] › e2e/areas.spec.js:4:1 › epics list opens and shows a new epic (1.4s)
  ✓  13 [mobile] › e2e/areas.spec.js:20:1 › roadmap view renders with the project tasks (989ms)
  ✓  15 [mobile] › e2e/areas.spec.js:37:1 › the notifications bell opens and closes (459ms)
  ✓  14 [mobile] › e2e/areas.spec.js:28:1 › the Build area renders the agents page (1.2s)
  ✓  16 [mobile] › e2e/areas.spec.js:47:1 › the theme toggle switches between dark and light and remembers it (451ms)
  ✓  17 [mobile] › e2e/auth.spec.js:7:5 › signed out › wrong password is rejected (558ms)
  ✓  19 [mobile] › e2e/auth.spec.js:25:5 › signed out › a private page sends you to sign in (347ms)
  ✓  18 [mobile] › e2e/auth.spec.js:16:5 › signed out › signing in lands on the workspace (650ms)
  ✓  20 [mobile] › e2e/auth.spec.js:32:1 › a saved session opens the workspace directly (359ms)
  ✓  22 [mobile] › e2e/project.spec.js:4:1 › create a project and see it on the board and the home page (1.0s)
  ✓  21 [mobile] › e2e/mobile.spec.js:8:1 › the board and the task page do not scroll sideways at 375px (1.4s)
  ✓  23 [mobile] › e2e/task.spec.js:4:1 › create, open, edit, comment on and move a task (1.8s)

  23 passed (12.2s)
```

Runs 1 and 2: `23 passed (13.3s)`, `23 passed (12.9s)`.

## Other checks

```
$ cd frontend && npx vitest run
 Test Files  68 passed (68)
      Tests  418 passed (418)

$ cd frontend && npm run lint
> eslint . --max-warnings 0     (clean)

$ python -m pytest backend/tests/ -q -n 4
1092 passed, 80 warnings in 59.68s
```

`backend/tests/test_e2e_seed.py` was written first and failed with a missing `backend.e2e_seed` module before the implementation.

## Findings the suite surfaced (fixed here)

- Epic page: at 375px the title collapsed to zero width (header row could not wrap). Fixed in `frontend/src/pages/EpicPage.jsx`; the epics spec fails without it on the `mobile` project.
- The notifications bell had no accessible name or keyboard access. Added `role="button"`, `aria-label="Notifications"`, `aria-expanded`, Enter/Space (vitest test added in `shell.test.jsx`).
- Flake root cause: `vite preview` (Node's 5 s keep-alive) made Chrome intermittently fail requests ("Failed to fetch"), 1–3 of ~20 tests per run. Serving the production nginx image from compose removed it (6/6 then 3/3 clean runs).

Not run: the GitHub workflow itself (needs a push).
