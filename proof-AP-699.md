# Proof AP-699 — realistic sample dataset

Isolated stack only: throwaway `postgres:16-alpine` container `ap-ap699-db` on port 55699 (removed afterwards), backend on :8199, vite on :3199, temp attachments dir. The running `agentira-local-prod` stack and daemon were never touched. Seeder writes rows directly — no services that dispatch, no daemon, runtime, LLM, GitHub or network call.

## 1. Seed timing (empty Postgres, fresh DB with a second unrelated org already in it)
```
$ python scripts/seed_test_data.py
seeded preview org in 0.9s
login →  preview / preview1234
```
Test `test_seed_volumes_and_login` also asserts < 60 s.

## 2. Row counts (preview org, straight from SQL)
```
preview org 1715b770cd16
  profiles                11
  projects                 4
  project_members         16
  epics                   28
  milestones              13
  tasks                  784
  task_dependencies       77
  activities            4313
  task_commits           580
  attachments             66
  notifications           24
  forge_agents             9
  forge_runs (preview)  50
  forge_runs non-terminal 0
  forge_messages (runs) 346
  tasks per project: ['Agentira Platform=600', 'Easy ESG=60', 'Fresh Start=4', 'Mobile App=120']
  long desc >=2000 chars: 306
OTHER orgs: tasks/projects/profiles/orgs = (3, 1, 8, 1)
```
`forge_runs non-terminal 0` → every seeded run is COMPLETED/FAILED. Run events = `forge_messages` rows (346).

## 3. Idempotency
```
$ python scripts/seed_test_data.py        # 2nd run
preview org already seeded — nothing to do (use --reset to rebuild)
```
Counts unchanged (test `test_seed_twice_is_idempotent` compares every table).

## 4. `--reset` scope
Other org ("Other Co", 3 tasks, 1 project, 8 profiles) created before seeding. One preview task renamed `EDITED BY HAND`, then:
```
$ python scripts/seed_test_data.py --reset
seeded preview org in 1.0s
```
```
  tasks per project: ['Agentira Platform=600', 'Easy ESG=60', 'Fresh Start=4', 'Mobile App=120']
  long desc >=2000 chars: 306
OTHER orgs: tasks/projects/profiles/orgs = (3, 1, 8, 1)
```
- `diff counts_before_reset counts_after_reset` → identical (deterministic ids/content).
- `EDITED BY HAND` rows left: 0 (preview org rebuilt).
- Other org untouched: `other 0, other 1, other 2`, same project/profile/org counts.
Test `test_reset_only_touches_preview_org` asserts the same on testcontainers Postgres.

## 3. Tests / lint
```
backend/tests/test_sample_data.py  4 passed
ruff check: All checks passed
```

## 5. Screenshots (seeded "Agentira Platform", 600 tasks) — attached: `board.png`, `task-long.png`
Real UI (vite + uvicorn), logged in as `preview`. Board (600 cards across 5 columns) ready in ~1.9 s; long task page (AP-81, 7.9k-char markdown description) in ~2.2 s.
API calls, board: /api/projects/{id}/board, members, profiles, epics, projects, notifications, activity?limit=20 (+ /api/home*, forge/runs on shell load). Task page: tasks/{id}, activity, runs, commits, repos, links, tasks?project_id, milestones, proof (+ shell calls). No code in this PR touches the frontend, so request counts are unchanged.
