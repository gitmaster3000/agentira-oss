# AGENTIRA VISION — From Vibe Code to Production

> **Purpose of this document:** This is the architectural north star for anyone
> (human or agent) working on the Agentira codebase. Read this before starting
> any feature. Every implementation decision should move toward this vision,
> never away from it. If a task conflicts with this document, stop and raise it.

---

## 1. WHAT AGENTIRA IS

Agentira is a platform that turns vibe-coded, prototype-quality software into
production-ready, deployable applications using verified AI agents.

The user has a GitHub repo that "works on localhost" but has no tests, no CI/CD,
hardcoded secrets, no error handling, and no deployment. Agentira audits the
codebase, plans the remediation, assigns AI agents to fix every issue, verifies
every fix through evidence-gated state transitions, and deploys the result to
production — all visible and manageable through a Kanban board the user already
understands.

**One-liner:** "From vibe code to production code."

**The buyer:** indie hackers, vibe coders, non-technical founders, product
managers — anyone who built something that works but isn't shippable.

**The wedge vs. competitors:**
- Paperclip (55k stars): orchestrates agents as a "company" but doesn't care
  about software quality. No audit, no verification, no deployment pipeline.
- Multica (13k stars): orchestrates engineering agents with skills compounding
  but is engineer-shaped. No design-to-deploy pipeline, no production-readiness
  workflow, no non-engineer UX.
- Bolt/Lovable/v0: generate prototypes but can't get them to production.
- Cursor/Claude Code: powerful single-agent tools but no PM layer, no
  verification, no deployment.

**Agentira's moat:** every agent claim is verified by the system, not by the
agent's word. The platform doesn't trust agents — it trusts evidence.

---

## 2. CORE ARCHITECTURE

### 2.1 What exists today

| Layer                    | Status   | Notes                              |
|--------------------------|----------|------------------------------------|
| Kanban board             | Working  | Projects, columns, drag-and-drop   |
| RBAC                     | Working  | Admin / Member / Viewer            |
| Audit log                | Working  | Needs structured format            |
| MCP server (15+ tools)   | Working  | Agents can still cheat             |
| Agent profiles           | Working  | No capability constraints yet      |
| Daemon + runtime detect  | Working  | Needs per-task isolation            |
| Runs concept             | Working  | No verification                    |

### 2.2 Two-door architecture

The backend has two entry points into one services layer:

```
MCP Server (mcp_server.py)  ──┐
                               ├──▶  services.py  ──▶  Database
REST API  (rest_api.py)    ──┘
```

All business logic lives in `services.py`. MCP tools and REST endpoints are
thin wrappers that validate input, call services, and format output. This
principle must be maintained in all new work.

### 2.3 The trust architecture (non-negotiable)

Agentira's core design principle is: **the system verifies, the agent executes,
the human audits.**

This manifests in three rules that apply to EVERY feature:

1. **Agents cannot assert completion.** Forward state transitions (to "review",
   to "done") are triggered by verified evidence (GitHub webhooks, CI results,
   AC checks), never by agent tool calls.

2. **Every claim is checkable.** PR links are validated against the GitHub API.
   Acceptance criteria have machine-checkable types. Test results are real CI
   output, not agent assertions.

3. **The container is the security boundary.** Agents run inside per-task
   containers with filesystem, network, and compute limits enforced at the
   kernel level. The agent's own permission config is best-effort; the container
   is the real enforcement. This is what makes the trust model uniform across
   Claude Code, Codex, OpenClaw, and any future agent CLI.

---

## 3. THE UNIVERSAL WORKFLOW PATTERN

Every workflow in Agentira follows the same shape:

```
Trigger  →  Audit/Analyze  →  Plan  →  Execute  →  Verify  →  Deliver
```

What changes between workflows:
- Which agent profiles do the work
- Which columns the board has
- Which MCP tools each agent can call
- Which AC check types verify the output
- What the trigger is (repo URL, website URL, document, etc.)
- What the container image contains (dev tools, SEO tools, etc.)

The board, RBAC, audit log, verified state machine, container isolation, daemon,
and Conductor are IDENTICAL across all workflows. Workflows are differentiated
only by templates, never by platform changes.

---

## 4. WORKFLOW TEMPLATES

A workflow template is a declarative file (YAML) that defines a complete
workflow without any platform code changes.

```yaml
name: "Production Readiness"
version: "1.0"
trigger:
  type: "github_repo_url"
  label: "GitHub Repository URL"

columns:
  - Audit
  - Planning
  - Ready
  - In Progress
  - Review
  - Deploy
  - Done

agents:
  - name: Auditor
    role: auditor
    model: sonnet
    system_prompt_file: "prompts/production_readiness/auditor.md"
    allowed_tools:
      - claim_task
      - comment
      - attach_file
      - block_task
    container_image: "agentira/dev-tools"

  - name: Planner
    role: planner
    model: sonnet
    system_prompt_file: "prompts/production_readiness/planner.md"
    allowed_tools:
      - create_task
      - comment
      - block_task

  - name: Implementer
    role: implementer
    model: opus
    system_prompt_file: "prompts/production_readiness/implementer.md"
    allowed_tools:
      - claim_task
      - link_pr
      - comment
      - block_task
    container_image: "agentira/dev-tools"

  - name: Reviewer
    role: reviewer
    model: different_than_implementer
    system_prompt_file: "prompts/production_readiness/reviewer.md"
    allowed_tools:
      - comment
      - block_task

  - name: CI/CD Setup
    role: implementer
    model: sonnet
    system_prompt_file: "prompts/production_readiness/cicd.md"
    allowed_tools:
      - claim_task
      - link_pr
      - comment
      - block_task
    container_image: "agentira/dev-tools"

  - name: Deploy
    role: deployer
    model: sonnet
    system_prompt_file: "prompts/production_readiness/deployer.md"
    allowed_tools:
      - claim_task
      - comment
      - block_task
    container_image: "agentira/deploy-tools"

ac_check_types:
  - name: test_passes
    description: "Named test passes in CI"
    runner: "pytest {test_name} --tb=short"
    pass_condition: "exit_code == 0"

  - name: no_secrets_in_source
    description: "No hardcoded secrets detected"
    runner: "trufflehog filesystem . --json"
    pass_condition: "output_lines == 0"

  - name: endpoint_returns
    description: "HTTP endpoint returns expected status"
    runner: "curl -s -o /dev/null -w '%{http_code}' {url}"
    pass_condition: "output == {expected_status}"

  - name: file_exists
    description: "Required file exists in repo"
    runner: "test -f {path}"
    pass_condition: "exit_code == 0"

  - name: lint_passes
    description: "Linter exits clean"
    runner: "npx eslint . --max-warnings 0"
    pass_condition: "exit_code == 0"

  - name: build_succeeds
    description: "Project builds without errors"
    runner: "npm run build"
    pass_condition: "exit_code == 0"

conductor:
  auto_assign: true
  pick_strategy: "highest_priority_unblocked"
  respect_dependencies: true
  notify_on_block: true
  digest_schedule: "daily"
```

### 4.1 Template loading

When a user creates a "New Production Readiness Project":
1. The template YAML is loaded
2. A project is created with the template's columns
3. Agent profiles are registered (or reused if they already exist)
4. AC check type runners are registered for this project
5. The initial Audit issue is created and assigned to the Auditor agent
6. The Conductor begins monitoring the project

### 4.2 Example workflow templates (future — DO NOT BUILD YET)

These exist to illustrate the pattern. Only build these when there is user
demand. The architecture must support them, but the implementations wait.

| Template               | Trigger         | Auditor checks                                    |
|------------------------|-----------------|---------------------------------------------------|
| Production Readiness   | GitHub repo URL | Tests, secrets, CI, errors, deps, build, deploy   |
| SEO Optimization       | Website URL     | Meta tags, speed, structure, links, sitemap        |
| Accessibility (a11y)   | Website URL     | WCAG violations, contrast, aria, semantics         |
| Security Hardening     | GitHub repo URL | CVEs, misconfigs, exposed secrets, OWASP           |
| Documentation          | GitHub repo URL | README, API docs, comments, changelog              |
| Design System Audit    | Figma + repo    | Inconsistent tokens, components, spacing           |
| Landing Page           | Brief (text)    | N/A — generative, not remediation                  |

---

## 5. THE VERIFIED STATE MACHINE

### 5.1 State transitions

```
                  ┌─────────────────────────────────────────┐
                  │                                         │
                  ▼                                         │
┌──────┐    ┌─────────┐    ┌───────────┐    ┌────────┐    │
│ Todo │───▶│ Claimed │───▶│ In Review │───▶│  Done  │    │
└──────┘    └─────────┘    └───────────┘    └────────┘    │
                  │                │                        │
                  │                │                        │
                  ▼                ▼                        │
             ┌─────────┐                                   │
             │ Blocked │───────────────────────────────────┘
             └─────────┘
```

### 5.2 Who can trigger each transition

| Transition              | Triggered by                              | NOT by           |
|-------------------------|-------------------------------------------|------------------|
| Todo → Claimed          | Agent calls `claim_task`                  |                  |
| Claimed → In Review     | GitHub webhook: PR opened + CI green      | Agent tool call  |
| In Review → Done        | GitHub webhook: PR merged + DoD passes    | Agent tool call  |
| Any → Blocked           | Agent calls `block_task` with reason       |                  |
| Blocked → Claimed       | Human unblocks or agent retries            |                  |
| In Review → Claimed     | PR closed without merge OR DoD fails       |                  |

### 5.3 Evidence required for each forward transition

**Claimed → In Review:**
- PR exists (verified via GitHub API, not agent assertion)
- PR's head branch matches pattern `task/{task_id}` or `feat/{task_id}-*`
- PR's repo matches the project's configured repo
- PR is not already linked to a different task
- CI status on the PR is "success"
- PR diff is non-empty

**In Review → Done:**
- PR is merged (GitHub webhook `pull_request.closed` with `merged: true`)
- Merger is a human (non-bot author) OR human has pre-approved auto-merge
- All machine-checkable ACs pass (`verify_dod` function)
- Manual ACs have been approved by a human via `human_approve_ac`

### 5.4 The `block_task` tool

Agents SHOULD block rather than fake. Blocking is a first-class, no-shame
action. The structured reasons are:

- `spec_unclear` — acceptance criteria are ambiguous or contradictory
- `dependency_missing` — another task must complete first
- `tooling_failure` — a tool or service the agent needs is broken
- `scope_too_large` — the task is too big for a single agent session
- `requires_human_judgment` — a product/business decision is needed
- `environment_broken` — the container or runtime is misconfigured

Each block writes to the audit log and surfaces in the user's notification
digest. The Conductor skips blocked tasks and picks the next unblocked one.

---

## 6. CONTAINER ISOLATION

### 6.1 Per-task containers

Every task execution happens inside a Docker container provisioned by the
daemon. The container provides:

- **Filesystem:** Repo mounted read-only at `/repo-ro`. Task working copy at
  `/workspace` (writable). Nothing else is accessible.
- **Network:** Egress allowlist only — npm/pip registries, GitHub API, the
  Agentira MCP server, localhost dev services. Everything else blocked.
- **Secrets:** Injected as env vars at container start, scoped to the task's
  branch. Agent cannot reach the production secret store.
- **Compute:** CPU and memory caps. Wall-clock timeout (configurable per
  template, default 30 minutes). Runaway agents die naturally.
- **Cleanup:** Container destroyed on task completion, failure, or timeout.
  Logs captured and attached to the task's audit trail before destruction.

### 6.2 Why the container is the security boundary

Different agent CLIs (Claude Code, Codex, OpenClaw) have different permission
models with different granularity. Instead of maintaining per-CLI configs that
may break with upstream changes, we enforce at the container layer:

- Claude Code: has rich `.claude/settings.json` — use it as a best-effort
  inner layer, but don't depend on it for security.
- Codex: has `--writable-roots` and sandbox modes — coarser but workable.
- OpenClaw/Antigravity: minimal permission config — rely entirely on container.

The container makes the trust model uniform regardless of which agent runs
inside it.

### 6.3 MCP tool access (the one place we DO get uniform control)

The Agentira MCP server is ours. Each agent connects with a token tied to its
role. The MCP server checks the token against the role's allowed tool list and
rejects unauthorized calls. This works identically for every agent CLI because
it's enforced server-side.

```
Agent  ──(MCP call with role token)──▶  Agentira MCP Server
                                              │
                                              ▼
                                    Check: is this tool in
                                    the role's allowed list?
                                              │
                                     ┌────────┴────────┐
                                     │                 │
                                   Yes               No
                                     │                 │
                                     ▼                 ▼
                                Execute tool     Return error:
                                                 "Tool not permitted
                                                  for role: reviewer"
```

---

## 7. AGENT PROFILES

### 7.1 Standard roles

Every workflow template uses agents from these standard roles. The template
specifies which model and system prompt each agent uses.

| Role         | Purpose                         | Can write code | Can move state forward | Can create tasks |
|--------------|----------------------------------|----------------|------------------------|------------------|
| auditor      | Analyze and report               | No             | No                     | No               |
| planner      | Create remediation issues        | No             | No                     | Yes              |
| implementer  | Write code to fix issues         | Yes            | No (PR triggers it)    | No               |
| reviewer     | Review PRs, find problems        | No             | No                     | No               |
| deployer     | Provision infra and deploy       | Yes (config)   | No                     | No               |
| conductor    | Orchestrate: pick, assign, nudge | No             | No                     | No               |

No role can move state forward. Only evidence moves state forward.

### 7.2 Cross-model review

The Reviewer agent MUST run on a different model than the Implementer. This is
the cheapest, highest-quality cheat detector. The Reviewer reads the diff cold,
without the Implementer's confused context.

The Reviewer specifically looks for:
- Empty function bodies or stub implementations
- Hardcoded test data that only passes the exact test case
- Mocks where real logic should exist
- Deleted or skipped assertions
- Commented-out code or TODO markers
- Tautological tests (`expect(true).toBe(true)`)
- Diff size mismatches (a "build user inbox" task with 12 lines of change)

### 7.3 Agent reputation tracking (future — design for it, don't build it yet)

Per-agent stats: PRs merged, PRs reverted, ACs failed at review, hallucinated
artifacts caught, tasks blocked. Stored in the database, surfaced on the agent
profile page. Used to decide which models/configs are reliable for which roles.

---

## 8. THE PRODUCTION READINESS PIPELINE (first workflow to ship)

### 8.1 User flow

1. User clicks "New Production Readiness Project"
2. Pastes a GitHub repo URL
3. Agentira creates the project with audit → plan → ready → in progress →
   review → deploy → done columns
4. Auditor agent runs in a container, produces `AUDIT_REPORT.md`
5. Report appears as an attachment on the Audit issue. Dashboard card shows
   health score (red/amber/green per category).
6. Planner agent reads the report, creates 10-30 prioritized issues in the
   "Ready" column, each with machine-checkable ACs.
7. User reviews the backlog. Can reorder, delete, edit, or approve.
8. Conductor auto-assigns issues to agents. Issues flow across the board.
9. User gets notifications: "5 fixed, 1 blocked (needs your input), 4 remaining"
10. CI/CD Setup issue completes: repo now has GitHub Actions, Dockerfile,
    branch protection.
11. Deploy issue unblocks. Agent provisions infra, deploys, runs smoke test.
12. Health check AC auto-verifies the app is live.
13. Board shows all issues in Done. Health score: green.
14. App is live at a production URL with monitoring and rollback.

### 8.2 What the Auditor checks

- Test coverage (0%? 40%? 80%?)
- Hardcoded secrets (trufflehog)
- Error handling patterns (unhandled promises, bare excepts, no error boundaries)
- Security scan (npm audit / pip audit, basic OWASP)
- Dependency freshness (outdated packages, known CVEs)
- Build health (does it build? does lint pass?)
- Docker/deployment readiness (Dockerfile? env vars documented?)
- Code structure (is there a clear entry point? reasonable file organization?)
- Accessibility basics (if web app)

### 8.3 What the Planner generates (example issues)

```
Issue: "Extract 3 hardcoded secrets to environment variables"
Priority: Critical
AC: [{check_type: no_secrets_in_source}, {check_type: file_exists, path: ".env.example"}]

Issue: "Add error boundaries to all React routes"
Priority: High
AC: [{check_type: test_passes, test_name: "error-boundary"}, {check_type: build_succeeds}]

Issue: "Set up GitHub Actions CI pipeline"
Priority: High
AC: [{check_type: file_exists, path: ".github/workflows/ci.yml"}, {check_type: lint_passes}]

Issue: "Add integration tests for auth flow"
Priority: Medium
AC: [{check_type: test_passes, test_name: "auth-integration"}]

Issue: "Deploy to production"
Priority: Low (blocked until all above are Done)
AC: [{check_type: endpoint_returns, url: "$DEPLOY_URL/health", expected_status: 200}]
```

---

## 9. THE PROJECT DASHBOARD CARD

A single React component displayed at the top of each Production Readiness
project board. Shows:

- **Health score** from the audit: red/amber/green per category
  (Security, Tests, Error Handling, Dependencies, Build, Deploy Readiness)
- **Progress bar:** 12/15 issues done, 2 in review, 1 blocked
- **Agent activity:** which agents are currently working, on what
- **Estimated time remaining** based on average completion velocity
- **"Deploy" button** — enabled only when all issues are Done and CI is green
- **Before/after diff** — health score at audit time vs. current

This is a SMALL addition to the existing board UI. Not a separate page, not a
separate product. One component.

---

## 10. INCREMENTAL BUILD SEQUENCE

Each increment is shippable and useful on its own. Do not skip ahead. Do not
combine increments. Each one must be complete (tested, reviewed, merged) before
starting the next.

### Increment 1 — Verified State Machine (weeks 1-2)
Stop agents from cheating. PR validation, evidence-gated transitions,
`block_task` tool, structured audit entries.
**Depends on:** nothing (current codebase)
**Delivers:** trustworthy task completion

### Increment 2 — Machine-Checkable DoD (weeks 3-4)
Add `check_type` to acceptance criteria. `verify_dod` function gates
review → done. Failed ACs bounce the issue back.
**Depends on:** Increment 1
**Delivers:** "done" means "actually works"

### Increment 3 — Container Isolation Per Task (weeks 5-8)
Docker container per task via the daemon. Filesystem, network, compute
isolation. Container logs in audit trail.
**Depends on:** Increment 1
**Delivers:** agents cannot damage anything outside their task

### Increment 4 — Codebase Auditor Agent (weeks 9-11)
The Auditor agent + "Production Readiness" project type. Runs checks,
produces AUDIT_REPORT.md, surfaces health score. THIS IS THE FREE TIER
PRODUCT — the first thing you can show the outside world.
**Depends on:** Increment 3 (runs in container)
**Delivers:** "point us at your repo, we tell you what's wrong"

### Increment 5 — Remediation Planner Agent (weeks 12-13)
Reads audit report, creates prioritized issues with machine-checkable
ACs. Template-aware from day one (reads template's AC check types and
agent roster, not hardcoded).
**Depends on:** Increments 2, 4
**Delivers:** one-click remediation plan

### Increment 6 — Conductor / Automated Execution (weeks 14-16)
Auto-picks issues, auto-assigns to agents, monitors progress, sends
digest notifications. Cross-model review enforced. Template-aware
(reads template's agent roster for assignment).
**Depends on:** Increments 1, 2, 3, 5
**Delivers:** "agents fix your code while you sleep"

### Increment 7 — CI/CD Setup Agent (weeks 17-19)
Detects stack, generates GitHub Actions, Dockerfile, .env.example,
branch protection. Delivered as a verified PR.
**Depends on:** Increment 6 (runs through the pipeline)
**Delivers:** professional CI/CD from zero config

### Increment 8 — One-Tap Deploy (weeks 20-23)
Deploy agent provisions Railway/Fly.io/Vercel infra, configures
monitoring (Sentry), adds rollback, runs post-deploy health check.
**Depends on:** Increment 7
**Delivers:** the complete "vibe code to production" story

### The workflow template system
Design for templates from increment 5 onward (Planner and Conductor
read from template config, not hardcoded logic). The template YAML
schema and loader can ship as a small task alongside increment 5.
DO NOT build non-Production-Readiness templates until the first
workflow has paying users.

---

## 11. WHAT NOT TO BUILD

This list is as important as the build list. These are explicitly deferred
and must not be worked on, designed for in detail, or scope-crept into
existing increments.

- **Generic work management** (marketing, video, SAP, etc.) — workflow
  templates enable this architecturally; do not build specific templates
  until users request them.
- **Template marketplace** — Series A feature, not MVP.
- **Team features / multi-user collaboration** — solo users first.
- **Mobile native app** — PWA is sufficient.
- **Agent reputation system** — design the schema, don't build the UI.
- **OpenClaw/Codex fork** — wrap CLIs through adapters, never fork.
- **Custom field builder / pipeline builder** — opinionated defaults only.
- **Clipmart-style "downloadable companies"** — Paperclip's play, not ours.
- **Natural language task creation** — our tasks are created by the Planner
  agent from audit results, not by users typing in natural language.
- **Real-time collaboration / multiplayer editing** — solo-user product.

---

## 12. DESIGN PRINCIPLES FOR ALL NEW CODE

1. **Services layer is the single source of truth.** All business logic in
   `services.py`. MCP tools and REST endpoints are thin wrappers.

2. **Evidence over assertion.** If an agent claims something happened, the
   system verifies it against an external source (GitHub API, CI results,
   filesystem checks). Never trust the agent's word.

3. **Container-first isolation.** Don't write agent-CLI-specific permission
   configs for security. Use the container. CLI configs are best-effort inner
   layers only.

4. **Template-aware, not hardcoded.** The Planner and Conductor read from
   template config. When adding a feature, ask: "does this work for any
   template, or only for Production Readiness?" If only PR, refactor.

5. **Audit everything.** Every state change, every tool call, every PR link,
   every DoD check, every block — structured JSON in the audit log.

6. **Small issues.** If a task would take an agent more than 60 minutes of
   focused work, split it. Large tasks get faked. Small tasks get done.

7. **Block, don't fake.** Agents should be explicitly encouraged (in system
   prompts) to call `block_task` rather than produce low-quality output.
   Blocking is cheaper than reverting a bad merge.

8. **Cross-model review.** Reviewer and Implementer must use different models.
   Same-model review is theater.

9. **Progressive disclosure.** The user sees the board and the dashboard card.
   The audit log, container logs, agent reasoning, and PR diffs are available
   on click-through but not in the primary view.

10. **No premature generalization.** Build for Production Readiness first.
    Generalize only when the second workflow template is needed and funded by
    user demand.

---

## 13. BUSINESS MODEL

### Pricing tiers

| Tier        | Price         | What the user gets                                   |
|-------------|---------------|------------------------------------------------------|
| Free        | CHF 0         | Codebase audit (health report only). No remediation. |
| Pro         | CHF 49/mo     | Audit + automated remediation. Limited runs/month.   |
| Team        | CHF 99/mo     | Unlimited runs, custom templates, priority execution.|
| Enterprise  | Custom        | Self-hosted, SLA, custom agent profiles.             |

### Unit economics

- COGS per audit: ~CHF 0.50–2.00 (LLM tokens + container compute)
- COGS per full remediation run: ~CHF 5–15 (depends on issue count and
  model used)
- Target gross margin: 75%+
- Free tier is the hook (show them how broken their code is). Paid tier
  is the fix.

### Growth loop

Every vibe-coded app that gets production-ized is a case study. "Built in
Bolt, shipped with Agentira" is a story people share. The before/after
audit scores are inherently shareable.

---

## 14. COMPETITIVE POSITIONING

| They say                                      | We say                                          |
|-----------------------------------------------|------------------------------------------------|
| Paperclip: "Run a zero-human company"         | We: "Ship a production-ready product"           |
| Multica: "Orchestrate your engineering agents" | We: "Turn your prototype into a real product"   |
| Bolt/v0: "Build an app in 30 seconds"         | We: "Ship the app you built in 30 seconds"      |
| Cursor: "The AI code editor"                  | We: "The AI production pipeline"                |

We don't compete on agent orchestration (Paperclip wins there). We don't
compete on IDE experience (Cursor wins there). We don't compete on prototype
generation (Bolt wins there). We compete on the gap between prototype and
production — the gap none of them fill.

---

## 15. SUCCESS CRITERIA

### Phase 1 success (after increment 4, ~week 11)
- Landing page live with GitHub OAuth
- Free audit available to anyone
- 50+ repos audited
- 20+ email signups for paid tier waitlist
- Zero agent-faked completions (verified state machine works)

### Phase 2 success (after increment 6, ~week 16)
- Paid tier live (CHF 49/mo)
- 10+ paying users
- Average remediation: 15 issues fixed per repo
- User NPS > 40

### Phase 3 success (after increment 8, ~week 23)
- Full pipeline: audit → fix → deploy
- 50+ paying users
- Second workflow template requested by users (signal to generalize)
- Privyr fully built and deployed through Agentira (the flagship demo)

---

## 16. PRIVYR AS THE DOGFOOD CUSTOMER

Privyr (an AI-powered CRM for small businesses) is being built as Agentira's
first "customer." The prototype is intentionally vibe-coded fast, then run
through the Production Readiness pipeline. This serves three purposes:

1. **Forces the pipeline to work on a real codebase**, not a toy demo.
2. **Produces the flagship case study**: "Privyr was vibe-coded in 3 days.
   Agentira made it production-ready in 2 weeks. Here's the before/after."
3. **Generates revenue independently** — Privyr is a SaaS product targeting
   CHF 99-149/mo per user. If Agentira-the-platform takes longer than
   expected, Privyr-the-product can still generate income.

Implementation agents working on Agentira should be aware that Privyr is the
first repo that will be audited, planned, remediated, and deployed through
the platform. Design decisions should be validated against: "would this work
for the Privyr codebase?"

---

*This document is the source of truth for Agentira's direction. It is a living
document — update it when strategic decisions change, but do not dilute the
core positioning ("from vibe code to production code") or the trust architecture
(evidence over assertion) without explicit human approval.*

*Last updated: 2026-05-05*
