# Agentira — the product, in plain words

*Written 2026-06-12, before the summer pause. For sharing, talking, reflecting, designing. No code in here — read `docs/PRD.md` for the full feature inventory and `docs/feature-workflow-editor.md` for the next big UI piece.*

---

## What is this?

Agentira is a **software team made of AI agents** — with you as the only human on it.

It runs wherever you want: the platform (board, agents, orchestration) can live in the cloud or on your own server; only a small **daemon** runs on the machine where your code actually lives. Your repositories never have to leave your computer for the team to work on them.

You describe what you want built, the way you'd brief a team lead. A planning agent breaks it into tasks with clear "definition of done" checklists. Implementer agents pick the tasks up, write the code in their own isolated workspaces, and commit it. A *different* agent reviews the work — and rejects it if the evidence doesn't hold up. When review passes, the system itself merges the branch. A documentation agent writes up what shipped. You open your laptop in the morning, read the report, and approve the one thing only a human should approve: the final merge into your blessed branch.

That's the whole idea: **full autonomy with a human in the loop** — the loop does the work, you do the judgment.

## What makes it different

**The system doesn't trust the agents. It verifies them.**
An agent saying "done" means nothing here. Tasks can only advance when evidence exists: the checklist is actually checked, a real branch with real commits exists, review actually passed. We learned this the honest way — one of our own agents claimed a commit that didn't exist, twice. The reviewing agent caught it, rejected the work, and sent it back. That moment is the product: the pipeline polices itself.

**The pipeline is the secret sauce — and it's configuration, not magic.**
The flow (backlog → todo → in progress → review → done), who reviews, what evidence each step requires, what happens when something is rejected — all of it lives in readable configuration files, not buried in code. Customers will be able to re-map who does what without being able to break the engine.

**It recovers on its own.**
If a finished task can't advance (missing evidence), the system bounces it back to the agent once with precise instructions. If a reviewer rejects work, it goes back to the implementer who owes the fix — with the reviewer's feedback attached. If a task stalls with no activity, a watchdog notices and an orchestrator agent (the "Conductor") decides: retry, reassign, or wake the human. Nothing is allowed to silently sit there.

**Built with itself.**
Agentira's own backlog lives in Agentira. The agents build the platform they run on. Every failure they hit becomes a bug task on the same board — the QA loop and the product are the same thing.

## The two faces of the product

- **Studio** — the work surface. Projects, a kanban board, tasks with checklists, epics, comments with @mentions, activity feeds, notifications. Looks like a project tracker; the difference is who's doing the work.
- **Forge** — the engine room. The agents themselves (their prompts, models, tools, schedules), their runs (what each agent actually did, where, and what it produced), live chat with any agent, and the Conductor's controls.

## What works today

- The full task pipeline, end to end: plan → implement → review → merge → document, driven automatically.
- Evidence gates on every transition — no faked progress.
- Self-correction: bounce-back on missing evidence, hand-back on rejection, a stall watchdog, escalation to the human when budgets run out.
- Cross-agent review — the reviewer is never the author.
- Isolated agent workspaces — each agent works in its own sandboxed folder and branch; agents can't see each other's (or your other projects') files.
- Multi-repo projects — one project can span backend + frontend repos; each task pins to exactly one.
- A real first product shipped through the loop is in progress (FitTrack, a small fitness tracker — the proof-of-dogfood project).
- Chat with any agent, watch any run live, full audit trail of everything every agent did.

## What's rough (honestly)

- Local/offline models (qwen via OpenClaw) time out too easily — the adapter needs real work.
- Agents sometimes commit but forget to push; the contract now demands proof, server-side enforcement is next.
- Some screens are still engineer-grade (run diagnostics, settings) — readable by us, not yet by a normal person.
- No installer yet — running it still means knowing Docker.

## What's coming

1. **The visual workflow editor** — see your pipeline as a living diagram (think n8n): columns as nodes, hand-offs as arrows, live task badges riding them, click anything to configure who reviews and which gates are on. The full design spec is written; this is the centerpiece of the upcoming UI redesign.
2. **UI redesign** — a full design pass over both faces of the product (the PRD documenting every current surface is done; design work can start from it directly).
3. **Agent skills** — drop-in capability packs for agents (e.g. a frontend agent that knows a design system), layered the same way agent tools already are: built-in, yours, and Agentira-managed.
4. **Server-side verification** — the platform independently confirms commits, branches and PRs exist before believing any agent's claim. The reviewer caught the fake commit; soon the server will catch it first.
5. **Morning report as a dashboard** — KPIs, wins, blockers, today's priorities as a proper screen (and PDF export), not a wall of text.
6. **Security hardening + a real installer** — bcrypt, locked-down CORS, mandatory secrets, then a one-command install so a stranger can run Agentira without us in the room.

## The one-sentence pitch

**A software team you hire by turning it on** — agents that plan, build, review and ship under a system that verifies everything, with you holding the only key that matters.

---

*Deeper reading: `docs/PRD.md` (every feature and setting, for the redesign) · `docs/feature-workflow-editor.md` (the visual pipeline editor) · `docs/run-state-machine.md` (how runs and recovery work) · `docs/mcp_layering.md` (how agent tools are layered).*
