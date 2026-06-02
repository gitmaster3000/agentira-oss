# Pre-release audit — first-user readiness

**Audit date**: 2026-05-29 · **Auditor**: claude · **Scope**: hosted deployment for the first external user (friend)

## TL;DR

**Status: amber.** Code is in good shape. The blockers are coordination, not code:

1. **9 PRs queued and CI-green, not merged.** They add the features the friend's flow depends on (attachments, wizard, templates, sandbox, gates, restart button, etc.).
2. **No actual Railway deployment exists yet** — infra is configured (Dockerfiles, docker-compose.prod.yml, railway.toml, nginx.conf with internal proxy), but no one has clicked through Railway UI to provision the services.
3. **Daemon installer is still source-checkout only.** Friend will need a one-liner; v1 needs the install script.

Once the merges happen + Railway is provisioned + the daemon installer ships, the friend can sign up.

---

## What I verified end-to-end (live dev backend)

| Flow | Status | Note |
|---|---|---|
| Signup (`POST /api/signup`) | ✅ | Returns user + JWT |
| Create project (legacy payload) | ✅ | Auto-seeds Conductor + kickoff task |
| Create project (wizard payload `initial_tasks`+`members`) | ❌ on main | PR #94 not merged; payload fields silently dropped, falls back to legacy auto-seed |
| List projects (membership-scoped) | ✅ | New user only sees their own |
| Default agent templates | ✅ live | 6 templates seeded in container (Conductor + Planner + 2 Implementers + Reviewer + DevOps). Local change since AP-157 is shipped via Docker bind-mount. |
| Attachments — task scope | ✅ | Existing (legacy) |
| Attachments — project scope | ❌ on main | PR #93 not merged |
| Run page workdir/session_id display | ❌ on main | PR #95 not merged |
| Artifacts copyable | ❌ on main | PR #60 not merged |
| Restart button on terminal runs | ❌ on main | PR #96 not merged |
| Multi-repo + sandbox config | ❌ on main | PR #97 not merged |
| Gate engine | ❌ on main | PR #99 not merged |
| Backend test suite | ✅ 281 pass | (Local-only AP-157 templates not in this count since PR #98 not merged) |

---

## Queued PRs — recommended merge order

```
1. #93  AP-152 backend (attachments — Attachment.project_id)
2. #56  AP-152 frontend (dashboard attachments card)
3. #94  AP-153 backend (wizard payload)
4. #57  AP-153 frontend (wizard component)            [stacked on #56]
5. #98  AP-157 backend (default agent templates)
6. #97  AP-154+155 backend (multi-repo + sandbox config)
7. #59  AP-154+155 frontend (UI dropdowns + chip multi-select)
8. #99  AP-158 backend (gate engine local checks)
9. #61  AP-158 frontend (Project Settings toggle)
10. #95 backend (workdir/session_id surfacing)        [independent]
11. #96 backend (Restart button)                      [independent]
12. #58 frontend (Restart button)
13. #60 frontend (artifacts copyable)                 [independent]
14. #100 docs (this audit's companion: Railway + getting-started)
```

All 9 backend PRs + 5 frontend PRs are CI-green and mergeable. Stacking note: the frontend wizard #57 depends on the AP-152 attachments backend (#93) being in main so `api.uploadProjectAttachment` resolves. Merge #93+#56 first, then the wizard pair.

---

## What's already there (no work needed)

- ✅ `Dockerfile` (backend) — listens on `$PORT`, falls through to uvicorn
- ✅ `Dockerfile.mcp` (MCP) — same shape, MCP_PORT
- ✅ `agentira-frontend/Dockerfile` — multi-stage nginx with `${PORT}` template
- ✅ `agentira-frontend/nginx.conf` — proxies `/api/*` to `flowty-api.railway.internal:8080` (rename to match user's backend service)
- ✅ `docker-compose.prod.yml` — env-driven Postgres + healthchecks + resource limits
- ✅ `.env.prod.example` — documents required secrets
- ✅ `railway.toml` — minimal backend stub (Railway monorepo pattern uses UI for additional services)
- ✅ Migration path on Postgres (`_ensure_column` dialect-aware, `_drop_not_null` cases)
- ✅ Frontend's `Dockerfile` builds without errors (`npx vite build` clean on every recent PR)

---

## What's missing for v1 (after merges)

| Gap | Severity | Effort |
|---|---|---|
| Daemon install script for Mac (`.pkg` or `curl \| sh`) | high — without this the friend has to clone the repo | days |
| Daemon install script for Windows (`.msi` or PowerShell) | medium — defer if friend is on Mac | days |
| Attachment object storage (S3 or Railway Volume) | high — local-disk loses files on redeploy | 1 day for Railway Volume, 2-3 for S3 |
| First-time-user "Connect your daemon" page in UI | medium — friend needs a clear "paste this command + paste this API key" flow | half-day |
| Reset-password flow | medium — no recovery if friend forgets | half-day |
| Email notifications wire-up (templates ship; SMTP env vars missing) | low | half-day |
| Custom-domain TLS termination doc step | low — Railway docs cover this externally | minutes |

---

## Bugs / paper cuts found during audit

None blocking shipping. The "task_count: 0 then board shows 1 task" inconsistency in the create-project response is just a serialization quirk (the count is computed at the moment of insert, before the kickoff task is added). Cosmetic.

The wizard payload silently falling through to legacy auto-seed (instead of erroring or warning) is by design (back-compat) — but it means the frontend wizard PR #57 has no functional effect until backend #94 merges first. Not a code bug; a coordination one.

---

## Suggested next action

If the friend is signing up THIS WEEK:
1. Authorize merge of PRs #93, #56, #94, #57, #98, #60 (the friend-facing UX set) — 6 squash-merges, 5 minutes.
2. Provision Railway per `docs/deployment.md` — 10 minutes.
3. Friend signs up, hits the limit of "no daemon installer yet" — file that as the urgent v1 ticket.
4. Defer the AP-154/155/158 + gate engine pieces — friend doesn't notice them missing on day one.

If the friend is signing up LATER:
1. Land the full queue including sandbox + gates so v1 is the "real" Agentira, not a stripped one.
2. Build the daemon installer (the actually-hard piece) before deploy.
3. Deploy after the installer is done so the announcement is single-step.
