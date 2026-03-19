# Agentira — Product Roadmap

> **Mission:** Make Agentira instantly usable by pilot teams and AI agents — online, stable, and feature-complete enough to replace Jira for agent-driven workflows.

---

## At a Glance

| Phase | Name | Status | Priority | Goal |
|---|---|---|---|---|
| 0 | Fix & Stabilize | In Progress | CRITICAL | Zero known blockers before deploy |
| 1 | Cloud Deployment & Go Live | Todo | CRITICAL | Public URL, TLS, migrated data |
| 2 | Core Features for Pilot Teams | Todo | HIGH | Useful for real teams and agents |
| 3 | Jira-Parity Feature Set | Backlog | HIGH | Competitive with Jira/Linear |
| 4 | Polish, Integrations & Scale | Backlog | MEDIUM | Delightful and extensible |

---

## PHASE 0 — Fix & Stabilize
**Task:** cd7d4d662eaf | **Status:** In Progress | **Priority:** Critical

**Goal:** Resolve all UX-breaking bugs before deployment. Nothing ships with these open.

### Tasks
| ID | Title | Priority | Status |
|---|---|---|---|
| 376cbd5f01d1 | Search does not work | HIGH | todo |
| c6bf4aa7ed4d | When lifting task to move, all other disappear | HIGH | todo |
| 914e97844f28 | Checks for create task — MCP input validation | HIGH | todo |
| a86987a2aff6 | Bug: Global page scroll broken + column border clipped | MEDIUM | todo |
| a8fcff2b4efb | Remove redundant cancel/save buttons from task | MEDIUM | in_progress |

### Definition of Done
- [ ] All 5 tasks above are done
- [ ] No critical or high bugs remain on the board
- [ ] Smoke test: create, move, search, open task — all work cleanly
- [ ] MCP bots cannot pass invalid assignees without a clear error

---

## PHASE 1 — Cloud Deployment & Go Live
**Task:** 46c0589ae4c3 | **Status:** Todo | **Priority:** Critical
**Parent:** e33ed5aca289 (Productize & Go Live)

**Goal:** Agentira accessible at a public URL with TLS and migrated data.

### Deployment Sequence

#### Step 1 — Database
- [ ] Choose cloud host: Railway / Supabase / Render / AWS RDS / VPS
- [ ] Provision DB instance
- [ ] Export + migrate existing data; verify row counts
- [ ] Run all schema migrations against cloud DB

#### Step 2 — Backend + MCP
- [ ] Containerize backend (Dockerfile)
- [ ] Deploy backend to cloud host
- [ ] Deploy MCP server (same or separate host)
- [ ] Configure env vars: DB URL, secret keys, CORS origins
- [ ] Smoke test REST API: GET /api/projects, POST /api/tasks
- [ ] Smoke test MCP: list_projects, create_task, get_me

#### Step 3 — Frontend
- [ ] Build production bundle (npm run build)
- [ ] Deploy to Vercel / Netlify / Cloudflare Pages or nginx on VPS
- [ ] Point frontend API base URL to deployed backend
- [ ] Verify zero CORS errors in browser

#### Step 4 — Domain & TLS
- [ ] Assign domain (e.g., app.agentira.io)
- [ ] Configure DNS to cloud host
- [ ] TLS certificate (Let's Encrypt / provider-managed)
- [ ] HTTP to HTTPS redirect active

#### Step 5 — Security & Hardening
- [ ] Security audit: auth, input validation, CORS, rate limiting
- [ ] No dev secrets or debug flags in production build
- [ ] Uptime monitoring configured (UptimeRobot / Better Uptime)

#### Step 6 — Docs & Onboarding
- [ ] Docs revision complete (efd4ed8f5ab5)
- [ ] Customer master plan and onboarding guide ready (d14b6a8ea7da)
- [ ] MCP config docs updated to point to production URL

### Definition of Done
- [ ] App live at public URL with valid TLS
- [ ] Existing data migrated and intact
- [ ] 2+ pilot users/agents successfully log in and use the board
- [ ] No localhost in production config
- [ ] Uptime monitoring active

---

## PHASE 2 — Core Features for Pilot Teams
**Task:** a06fad900141 | **Status:** Todo | **Priority:** High

**Goal:** Minimum feature set for real teams and AI agents to manage projects effectively.

### Tasks
| ID | Title | Priority | Status |
|---|---|---|---|
| efd5e4c9923c | Task search & filter bar on Board | CRITICAL | in_progress |
| bf5097947b97 | Notifications & Activity Feed UI | HIGH | in_progress |
| 901795b52202 | Backlog and Roadmap views | HIGH | in_progress |
| 58089d7586d4 | Bot Creation UI & Bot Profile overhaul | HIGH | in_progress |
| 3ca1e0974aec | Audit Log & Activity Feed (backend) | HIGH | in_progress |
| 2f6aaeb17d6f | Subtasks: Parent-Child Task Hierarchy | HIGH | backlog |
| 7a04585c2765 | Plan: Revise auth framework (OAuth + Google login) | HIGH | todo |
| 356978edba04 | Plan & Scope: Sprints and Epics Feature Set | HIGH | todo |
| d14b6a8ea7da | Customer Master Plan & Onboarding Guide | HIGH | todo |
| efd4ed8f5ab5 | Docs revision | HIGH | todo |
| 28150fb90120 | Mobile Responsive UI Overhaul | MEDIUM | in_progress |

### Definition of Done
- [ ] All in_progress tasks above are done
- [ ] Subtasks feature shipped (backend + frontend + MCP)
- [ ] OAuth/Google login plan finalized and implementation started
- [ ] Sprint & Epic planning decisions documented with ADR
- [ ] 3+ external pilot users onboarded and actively using the tool
- [ ] Onboarding guide published at production URL

---

## PHASE 3 — Jira-Parity Feature Set
**Task:** 4f37bd7cb544 | **Status:** Backlog | **Priority:** High

**Goal:** Make Agentira a credible alternative to Jira for engineering teams and agent workflows.

### Tasks
| ID | Title | Priority |
|---|---|---|
| ee5a546260a0 | Sprint Planning & Iteration Management | HIGH |
| 4fbeaf1b35ad | Epics: Hierarchical Task Grouping | HIGH |
| 5b05d77d75c5 | Enhance Task Detail: DOD, Epic Link, Jira-Style Fields | HIGH |
| 26e8ca454ee3 | Roadmap / Timeline (Gantt) View | HIGH |
| 22b9d665c6a1 | Dynamic Permission Handling & Custom Roles | HIGH |
| 8dc95ef3a789 | Git Integration: Link Commits & PRs to Tasks | HIGH |
| a4490a38f8af | Story Points & Effort Estimation | MEDIUM |
| 04f2e5e321d6 | Agent Identity: Self-Configuration & Profile Editing | MEDIUM |

### Definition of Done
- [ ] Sprints can be created, started, and completed with burndown
- [ ] Epics group tasks with visible progress bars
- [ ] Tasks have type, story points, DOD checklist, start/due dates
- [ ] Gantt/Roadmap view works with drag-to-resize
- [ ] Git commits and PRs linked to tasks via webhook
- [ ] Custom roles can be created and assigned via UI

---

## PHASE 4 — Polish, Advanced Integrations & Scale
**Task:** 42d33ab2313f | **Status:** Backlog | **Priority:** Medium

**Goal:** Make Agentira delightful, extensible, and production-hardened for broader adoption.

### Tasks
| ID | Title | Priority |
|---|---|---|
| 8abef812a701 | @Mentions & Notifications in Comments | LOW |
| 6e302d97c9b2 | Webhooks & Outbound Event System (Slack, CI/CD) | LOW |
| 82c76cd54045 | Task Templates | LOW |
| a9bcd069d3ad | SSE Real-Time Updates (replace polling) | LOW |
| da33af2ede50 | Link Tasks — backend | LOW |
| e3875d6d91ed | Link Tasks — frontend | LOW |
| da260efabdc2 | MCP Proxy Shim: Global pip install | LOW |
| bcefd10bd317 | Better upload mechanism via MCP | LOW |
| 35ebb61947ea | Bot rules, workflows & identity files | LOW |
| d5f47800dde7 | Automated UI test suite | MEDIUM |
| de4934ece054 | Sort tasks by priority/type per column | LOW |
| be5e699025ad | Enhanced tags (autocomplete, enter-to-add) | LOW |
| 657edfc4dfa3 | Markdown rendering in description | LOW |
| e7e7b86c17e4 | Theme toggle: respect OS default | LOW |
| af2dcfd9a47f | Empty state illustrations | LOW |
| a3bbd7c92ee2 | Profile picture / avatar edit | LOW |

### Definition of Done
- [ ] @mentions trigger in-app notifications
- [ ] Outbound webhooks fire to Slack/Discord/CI on task events
- [ ] Task templates speed up recurring task creation
- [ ] SSE replaces polling for real-time board updates
- [ ] MCP shim installable with pip install agentira-shim
- [ ] UI test suite covers all major user flows

---

## Summary: Priority Stack

```
CRITICAL  Phase 0 (stabilize) + Phase 1 (go live)
HIGH      Phase 2 (pilot features) + Phase 3 (jira-parity)
MEDIUM    Phase 4 advanced features
LOW       Phase 4 polish & nice-to-haves
```

### Immediate Focus (this week)
1. Close Phase 0 bugs — search, drag, scroll, MCP validation
2. Start Phase 1 deployment planning — pick hosting, Dockerfile
3. Push in-progress Phase 2 features to done — notifications, backlog/roadmap, search/filter

### Next 2-4 Weeks
- OAuth + Google login implementation
- Subtasks feature shipped
- Sprint planning scoped and started
- Pilot users onboarded with feedback loop

---

Last updated: 2026-02-21 — Generated by Claude Architect
