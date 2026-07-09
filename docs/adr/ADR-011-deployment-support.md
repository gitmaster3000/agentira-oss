# ADR 011: Deployment Support — Scope, Target Taxonomy, Security Model

## Status

Proposed (AP-313)

## Context

Agentira runs agents against a task's repo, gets a verified PR merged, and
stops there. The user still has to deploy the result themselves. This is the
last mile of the "vibe code to production" story (`AGENTIRA_VISION.md` §8,
"THE PRODUCTION READINESS PIPELINE" — the `Deploy` column and `deployer` role
already exist in `templates/production-readiness.yaml` and
`AGENTIRA_VISION.md` §7.1, but nothing implements them yet).

This ADR is the PO/architect gate for the "Deployment support" epic. It blocks
implementation tasks AP-314–AP-321 (target registry, task fields, adapter
contract, Docker/Railway/GCP adapters, MCP tools + autonomy gating, deployer
agent template). Nothing downstream should start until the decisions below are
locked.

### First-customer framing

The first deliverable slice is **not** "push to Railway" — it's letting a user
see their app actually running, from inside Agentira, without leaving the
product. Concretely: an agent finishes a task, a local Docker deploy comes up
automatically, and the task/project UI shows a clickable preview URL the user
can click through and test right now. Cloud targets (Railway, GCP, k8s) matter
later, but they solve a different problem (a durable public URL) than the
phase-1 problem (closing the loop between "agent wrote code" and "user can see
it work" without a laptop full of `docker compose up` incantations).

## Decisions

### 1. Phase plan — local-first

**Phase 1 (this epic's real target):**
- `docker` adapter only (AP-317). Builds/`compose up`s the task's branch,
  returns a `http://localhost:<port>` (or container-network) URL.
- Preview URL surfaced directly on the Task/Project UI (AP-315) — this is the
  product surface, not an afterthought. A user opens a task, sees "Preview:
  <url> (running)", clicks it, tests the change.
- `test` environment only. No "prod" concept yet — phase 1 is inner-loop
  verification, not customer-facing hosting.
- Wired into the existing container-isolation model (`AGENTIRA_VISION.md`
  §6): the deploy adapter runs the target app in a sibling container/network
  reachable from the daemon host, not inside the agent's own sandboxed task
  container.

**Phase 2 (deferred, scope-gated behind phase 1 landing and a real customer
round-trip):**
- `railway` adapter (AP-318) — durable/public URLs, `test` and `prod`
  environments via Railway environments, reuses `railway.toml` (already in
  repo root) and the Railway CLI, token from env.
- MCP tools + autonomy-dial gating (AP-320) so an agent can trigger a deploy
  itself, gated `auto | ask | deny` through the Notifications + Autonomy Dial
  epic (`c10ea54a1209`).
- Deployer agent template + deploy-task DoD + seeded "set up deployments"
  task (AP-321).

**Deferred / stretch, not v1 at all:**
- `gcp_cloud_run`, `k8s` (AP-319). Build only after Docker + Railway prove out
  against a real customer. Do not design these in detail now — see VISION §11
  "WHAT NOT TO BUILD" precedent for over-scoping ahead of demand.

### 2. Target taxonomy

```
kind:        docker | railway | gcp_cloud_run | k8s
environment: test | prod
```

- `docker` only ever runs `test` (there is no "prod" meaning for a
  daemon-local container — that's what `railway`/`gcp`/`k8s` are for).
- `railway`, `gcp_cloud_run`, `k8s` support both `test` and `prod`, mapped to
  the target platform's own environment concept (Railway environments, GCP
  Cloud Run revisions/services, k8s namespaces).
- Capability model (for AP-316's adapter contract): each adapter declares
  which of `{DEPLOY, STATUS, ROLLBACK, LOGS}` it supports. `docker` supports
  all four locally; `railway`/`gcp`/`k8s` are expected to support all four
  against their respective control planes. A capability a target lacks is a
  no-op that surfaces as "unsupported" rather than a failure — mirrors the
  `RuntimeAdapter` pattern in `backend/forge/runtime_client.py` where each
  adapter implements the same abstract interface with backend-specific
  internals.

### 3. Secrets / security model

Same trust boundary the container-isolation model already establishes
(VISION §6.1, §6.3) — deployment secrets are just another category of
task-scoped secret, not a new mechanism:

- Deploy credentials (Railway token, GCP service account key, kubeconfig)
  live in environment variables the **daemon** supplies to the deploy
  adapter process — never in the agent's task container, never committed to
  the repo, never visible to the agent's own filesystem or MCP tool
  responses beyond a redacted "configured: yes/no".
- The `docker` adapter needs no external credential — it shells out to the
  local Docker/compose CLI available to the daemon host.
- `deploy.execute` (actually triggering a deploy) is gated by the autonomy
  dial (`auto | ask | deny`, Notifications epic `c10ea54a1209`, N-6/N-7) so a
  user controls whether an agent can autonomously push to a `prod`
  environment. `test`/`docker` deploys are expected to default to `auto` —
  low blast radius, same posture as running the test suite.
- No secret is ever echoed back through MCP tool results, task comments, or
  activity logs. Adapters return `{handle, url}`, `status`, `logs` — never
  the credential used to obtain them.

### 4. GitHub Deployments linkage

- When `gh`/GitHub is the source of truth for the repo (i.e. whenever a PR
  exists), the deploy adapter posts a GitHub Deployment + Deployment Status
  for the target commit, and the resulting `deployment_url`/PR preview link
  is what gets stored on the task (AP-315) — mirrors the existing
  `branch`/`pr_url` fields already on `Task` (`backend/models.py:475-476`).
- For `docker` phase-1 deploys with no PR yet (agent iterating on a task
  branch pre-review), there may be no GitHub Deployment object at all — the
  task's `deployment_url` field is populated directly by the adapter without
  a GitHub round-trip. GitHub Deployments become relevant once `railway`
  (phase 2) is in play and the deploy is tied to a reviewed PR.

### 5. Where settings live

- **Project-level default target(s)**: most projects have one deploy
  target per environment (one `docker` test target, later one `railway`
  test + one `railway` prod target). Store as rows tied to `project_id`.
- **Per-repo override**: `ProjectRepo` (AP-121, `backend/models.py:402`)
  already exists — projects can span multiple repos, and `Task.repo_name`
  picks which one a task targets. A `DeployTarget` should carry an optional
  `project_repo_id` FK (nullable — falls back to the project's `is_primary`
  repo, same default semantics `Task.repo_name` already uses) rather than
  inventing a separate per-repo concept. No new entity needed here — just a
  nullable FK onto the entity that already models "which repo."
- **Task-level result**: what actually got deployed, where, and its current
  status lives on `Task` itself (AP-315: `deployment_url`, `deploy_status`,
  target environment) — same pattern as the existing `branch`/`pr_url`
  columns, not a separate table.

### 6. Data-model sketch

```
DeployTarget (new table, backend/models.py)
  id                String(12) PK
  org_id            FK -> orgs.id, NOT NULL          # matches org-scoping on
                                                       # Task/ProjectRepo
  project_id        FK -> projects.id, NOT NULL
  project_repo_id   FK -> project_repos.id, nullable  # NULL = project's
                                                       # is_primary repo
  name              String(120)                 # user-facing label
  kind              Enum(docker|railway|gcp_cloud_run|k8s)
  environment       Enum(test|prod)
  config            Text (JSON blob)             # adapter-specific: compose
                                                   # file path, Railway
                                                   # project/env id, GCP
                                                   # project/region, etc. —
                                                   # no secrets, those come
                                                   # from env
  created_at        DateTime

Task (existing table, add columns — mirrors branch/pr_url at models.py:475-476)
  deploy_target_id   String(12) FK -> deploy_targets.id, nullable
  deployment_url     String(500), default ""
  deploy_status      String(20), default ""   # pending|running|live|failed|rolled_back
```

Repo-layer access via `backend/forge/repos/*` (per CONVENTIONS — no inline
`db.query` in services), REST CRUD for `DeployTarget` under Project Settings,
new `backend/forge/deploy/` module holding the `DeployAdapter` ABC (mirrors
`RuntimeAdapter` in `backend/forge/runtime_client.py:59`) plus one adapter
class per `kind`.

## Consequences

- Phase 1 ships a real, visible feature (click a link, see your app running)
  without needing any external account, token, or cloud dependency — fastest
  path to the "vibe code to production" loop closing for local dev.
- Deferring Railway/GCP/k8s means `DeployTarget.config` and the adapter
  capability model must be designed generically enough now that adding a
  `kind` later is a new adapter class, not a schema migration — this is why
  §6's `config` column is an opaque JSON blob rather than typed columns per
  adapter.
- `DeployTarget` reuses the existing `ProjectRepo` (AP-121) for per-repo
  overrides instead of inventing a parallel concept — one less migration,
  one less thing to keep in sync.
- `deploy.execute` autonomy gating (AP-320) depends on the Notifications +
  Autonomy Dial epic (`c10ea54a1209`) landing its `auto|ask|deny` primitive;
  if that epic slips, AP-320 defaults every deploy to `ask` rather than
  blocking on it.

## References

- `AGENTIRA_VISION.md` §6 (Container Isolation / secrets boundary), §7.1
  (deployer role), §8 (Production Readiness pipeline, deploy step), §11
  (What Not To Build — precedent for not over-building GCP/k8s early)
- `docs/architecture_decision_record.md` — ADR 007 (push+poll notification
  delivery, cited for the autonomy-dial notification path AP-320 will use),
  ADR 009 (Conversations, Turns & Runs — precedent for the Task/Run split
  this ADR's `deploy_status` piggybacks on, since a deploy is itself a
  run-adjacent side effect of a task), and ADR 010 (Per-Run Environment
  Isolation — the same provision-before/teardown-after shape as a `docker`
  deploy's lifecycle, worth reusing if the two turn out to share plumbing)
- `backend/forge/runtime_client.py:59` — `RuntimeAdapter` ABC, the pattern
  `DeployAdapter` (AP-316) mirrors
- `backend/models.py:402` — `ProjectRepo` (AP-121), reused by `DeployTarget`
  for per-repo overrides
- `templates/production-readiness.yaml` — existing `Deploy` column /
  `deployer` role, `railway.toml` — existing Railway config reused by AP-318
- Epic `c10ea54a1209` (Notifications + Autonomy Dial), epic `a93dc4064579`
  (RuntimeAdapter contract epic referenced by AP-316)

## DoD mapping (AP-313)

- [x] v1 scope + deferred list explicit — §1
- [x] secrets/security model defined — §3
- [x] target taxonomy + test/prod model defined — §2
- [x] GitHub Deployments linkage approach decided — §4
- [x] data-model sketch (settings + task fields) approved — §6
