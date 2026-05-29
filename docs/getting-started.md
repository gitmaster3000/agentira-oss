# Getting Started

A hands-on walkthrough for your first project on Agentira.

If you remember nothing else from this doc: **you don't talk to a model, you orchestrate a small team of agents that work on real code with traceable runs and artifacts.** Each agent has a persona, tools, and access. You drive the work by creating tasks, hitting Run, and commenting to steer.

---

## 0. What Agentira is, in one paragraph

Agentira is a self-hosted board for orchestrating AI coding agents on real software projects. You create a project, attach a brief (or a UI design, or both), and the Conductor — a built-in orchestrator agent — plans the work, picks the tech stack, and breaks it into concrete tasks. You assign your other agents (a backend agent, a frontend agent, whatever you want) to the spawned tasks. When you click **Run** on a task, the assigned agent works in its own git worktree, captures a diff, registers artifacts (PR / file / report), and finishes with a verdict. You see everything on the board: status, diff, artifacts, conversation, cost.

---

## 1. Sign up + connect your daemon

### Sign up

Visit your Agentira instance — the URL the operator gave you (something like `https://agentira.up.railway.app`, or a custom domain). Hit **Sign up**, pick a username + password (or click "Continue with GitHub/Google" if the operator wired OAuth).

That's it for the web side. The moment your account exists, your workspace already has six agents in it:

- **Conductor** — the orchestrator
- **Planner** — turns vague tasks into concrete DoDs + child tasks
- **Backend Implementer** — Python/FastAPI senior engineer
- **Frontend Implementer** — React/Vite/Tailwind senior engineer
- **Reviewer** — checks PRs against the DoD, won't approve faked progress
- **DevOps** — Docker, CI/CD, deploy

You can edit any of their prompts under **Forge → Agents**. The prompts are yours to tune.

### Install the daemon

The daemon is the bridge between the hosted backend and your local `claude` CLI. **It runs on your own machine** — the place where you want the agents to actually edit code.

Why local? Because the agents touch real files in real git repos that live on your laptop. The cloud backend coordinates; the daemon executes.

```bash
# Mac / Linux (one-liner installer — coming soon as part of the v1 release)
curl -fsSL https://your-instance.railway.app/install.sh | sh

# For now, run from source:
git clone https://github.com/<you>/agentira ~/agentira
cd ~/agentira/agentira-cli
pip install -e .
agentira daemon --backend-url https://your-instance.railway.app
```

When you start the daemon, paste the **API key** from your profile page (top-right avatar → **Settings → API key**). The daemon authenticates over WebSocket and stays connected.

```
WS connected + registered to wss://your-instance.railway.app/api/forge/daemon/ws
Daemon started — daemon_id=abc12345 runtimes=1
```

If the daemon can't find `claude` in your PATH, install it first (`npm i -g @anthropic-ai/claude-code` or follow Anthropic's instructions).

> **If your terminal closes, the daemon stops.** For longer sessions, run it under `tmux`, `screen`, or your OS's service manager. A signed Mac `.pkg` + Windows `.msi` that auto-start are part of the v1 release — same for the `curl | sh` installer above.

---

## 2. Create your first project

Click **New Project** in the Studio sidebar. You'll get a dialog with:

- **Name** — what you'll call it. The first letters become the prefix for task keys (e.g. "Voice Code App" → `VCA-1`, `VCA-2`).
- **Description** — a paragraph or two about what you want built. The Conductor reads this; be specific.
- **Attachments** *(use the attachments dropzone)* — drop in any UI designs, mockups, briefs, requirements docs. PNG, PDF, MD, anything. They land on the project itself (visible later on the project dashboard) — the Conductor reads them via the `list_project_attachments` MCP tool.

Hit **Create**.

### What you'll see immediately

- The Conductor is auto-added as a project member.
- A task titled **"Plan this project"** is already in the `todo` column, assigned to the Conductor.
- Your uploaded files are listed on the project dashboard under **Attachments**. You can drag in more there at any time.

You did not have to set any of that up.

### Teaching agents to use the project attachments

Prompts are configuration, not code — every agent's system prompt is editable in **Agent Settings → System prompt**. For the Conductor (and any other agent you want browsing project files), append something like:

> When you start work on a task, call `list_project_attachments(AGENTIRA_PROJECT_ID)` first. Text files come back inline. For binary files (PNGs, PDFs), use `read_attachment_text(<id>)` — for binary it returns a `download_url` and `api_key_env`; fetch with `curl -H "Authorization: Bearer $AGENTIRA_API_KEY" http://backend:8000<download_url>`.

The agent's API key is already injected as `$AGENTIRA_API_KEY` in its environment at dispatch time, so this works without extra setup.

---

## 3. Run the kickoff task

Open **"Plan this project"** and click the **Run** button.

The Conductor will:

1. **Read** the project description + any attachments (via the `list_attachments` and `download_attachment` MCP tools).
2. **Pick the tools and tech stack** with brief justification for each choice.
3. **Write a one-page plan** covering architecture, milestones, and risks. It registers the plan as a real artifact via `register_run_artifact(kind='report', label='Project plan')` — that's how it shows up on the Run page, not as scrollback text.
4. **Break the work into 3–8 child tasks** using `create_task`. Each gets a title, description, DoD items, and lands in the board.
5. Call `finish_run(outcome='succeeded')` when the plan + child tasks are in place.

If the brief is too vague, it'll call `finish_run(outcome='needs_input')` with a specific question instead. **Comment on the task** to answer — the comment lands in the agent's chat thread and resumes the run with your answer as the next turn.

### What you should see on the Run page

- **Status badge** flipping `pending → running → completed`
- **Conversation** streaming live (user prompt, assistant tool calls, tool outputs, final reply)
- **Artifacts** panel filling in with the registered plan
- **Diff** tab (will be empty for the kickoff run — no code was edited)
- **Tokens / cost** ticking up

When it's done, your board has 3–8 new tasks. Open them to see what the Conductor decided.

---

## 4. Assign your other agents and run the work

For each new task, set its **Assignee** to the agent you want working on it (backend agent for backend tasks, frontend for frontend, etc.).

> If you don't have those agents yet, create them under **Forge → Agents** first. Each one gets a name, a model (claude-sonnet-4-6 is a sane default), a system prompt that defines its persona ("You are a senior backend engineer who writes Python and PostgreSQL"), and an MCP toolkit. You can add agents to a project membership any time.

Then click **Run** on a task. The agent gets dispatched into its own git worktree (per the project's repo), reads the conventions, does the work, commits, opens a PR (if it knows how), and calls `finish_run`.

---

## 5. Comment to steer or resume

The single most important interaction on Agentira: **comment on a task to talk to its agent.**

- **Agent is running** → your comment **pauses** the run (clean SIGTERM, the conversation session is captured), then immediately **resumes** with your comment as the next turn — same run, same `run_id`. The agent has full context including your interruption.
- **Agent is paused / parked** (the run is `paused`, `needs_input`, or `blocked`) → your comment **resumes** the run with your message.
- **Run already finished** → your comment **starts a fresh turn** in the conversation. If that turn produces material work, a new run will crystallize automatically (see §7).

So: leave a `block_run` comment on a task that's running off the rails. Or answer a `needs_input` question. Or just say "actually, use pytest, not unittest." The agent reads it.

---

## 6. Stop, Pause, Resume — when each fires

- **Stop** (chat thread or Run page) on a running run → **Pause**. SIGTERM the agent, capture the session for resume, mark run `paused`. Your follow-up message resumes it. (There is no "hard cancel" button in the normal chat flow; cancel happens only when you explicitly cancel a run with no intent to resume.)
- **Stop** on a chat that has no run (yet) → terminates the in-flight turn.
- **Resume** (Run page) → re-dispatches the paused run with `claude --resume`, picking up exactly where it left off. The continuation prompt is short ("continue from where you paused") unless you also typed a steering message.
- All of the above survive a restart of the daemon or the backend — the in-flight turn is recorded on disk in `~/.agentira/inflight/<scope>.json`, and the daemon's startup orphan-reaper kills any zombie processes from prior runs.

---

## 7. What counts as a "run"

Every dispatch is a **turn**. A turn becomes a **run** (gets a card, a status, an outcome) only if it produces work. We don't bother you with a run card for every chat bubble.

A turn crystallizes into a run if **any** of these fire:

- A **non-empty git diff** in the worktree (per the project's *work-signal* mode: `working_tree` includes new untracked files; `tracked` only counts edits to known files; `committed` only counts a new commit). Default is `working_tree`, so an agent that creates a new file without `git add`-ing it is still credited.
- A call to `register_run_artifact` — the agent registered a PR, a deployed URL, a generated report, a key file.
- A call to `finish_run` — the agent explicitly declared an outcome (`succeeded` / `failed` / `blocked` / `needs_input`).

If a turn does **none** of those, it stays a chat turn — you'll see the conversation, but no run card. That's why "hey, what's your plan?" doesn't pollute the runs list.

> You can change the work-signal mode per project in **Project Settings → Run detection**.

---

## 8. The artifacts panel

When you open a Run page, look at the **Artifacts** panel — it's the answer to "what did this agent actually produce?". Real artifacts:

- **PR** (kind=`pr`) — link to a GitHub PR the agent opened
- **File** (kind=`file`) — a key file produced by the run
- **Report** (kind=`report`) — a markdown report (the Conductor's project plan uses this)
- **URL** (kind=`url`) — a deployed preview URL
- **Log** (kind=`log`) — a relevant log file path
- **Commit** (kind=`commit`) — a specific commit SHA

The chat transcript is *not* an artifact. If an agent says "here's the plan…" in chat but doesn't register it, the human reading the Run page tomorrow won't find it. The default agent system prompts encourage them to register artifacts; if yours forget, tell them in their system prompt.

---

## 9. The `/clear` slash command

In any chat thread, type `/clear` and hit send. It wipes:

- The agent's conversation memory for **this scope only** (`task:T`, or `chat:project:P`, or `chat:default`)
- The `claude --resume` session handle for this scope
- The persisted messages in this scope

It does **not** touch runs, diffs, artifacts, comments, or any other scope. Good when the agent has gone down a bad path and you want to start it over without losing prior work.

---

## 10. Glossary

| Term | What it actually means |
|---|---|
| **Conversation** | The agent's working memory for one *scope*. Continues across many runs in a task. Stored in `forge_conversations` + `forge_messages`. |
| **Scope** | The grain of a conversation: `task:<task_id>`, `chat:project:<project_id>`, or `chat:default`. |
| **Turn** | One dispatch — your message + the agent's response, sharing one `trace_id`. The atomic unit. |
| **Run** | An emergent span over the turns that did work. Has a status, an outcome, a diff, artifacts, and accounting. Some turns belong to a run; some are just chat. |
| **Artifact** | A concrete deliverable on a run — PR, commit, file, URL, report, log. Registered by the agent via `register_run_artifact`. |
| **Worktree** | The git working directory the agent has when it runs. Per `(agent, task)`, stable across all runs/chats in that task — `~/.agentira/agents/<agent>/home/repos/<project>/task-<task8>/`. |
| **Conductor** | The built-in workspace orchestrator agent. Auto-added to every new project. |
| **Daemon** | The host-side process that receives dispatches and spawns agent runtimes (claude, openclaw, etc.). |
| **Adapter** | The per-provider plugin inside the daemon that maps Agentira's contract onto the provider's native features (`--resume` for claude, `sessionKey` for openclaw, etc.). |

---

## 11. When something goes wrong

- **Agent doesn't reply** → check the daemon is running (`pgrep -f "agentira daemon"`) and the WS shows registered in its log.
- **Stop button doesn't seem to do anything** → the daemon may have restarted; on next dispatch it'll find no in-flight entry and the cancel becomes a no-op, but the run row still exists. You can manually mark the run `cancelled` from the Run page.
- **The agent is editing the wrong files** → check the project's **repo_path** in Project Settings → General. The worktree is created from this. If you have multi-repo (`AP-121` work), confirm the task's `repo_name` points at the right one.
- **`--resume` says "No conversation found with session ID"** → rare since ADR 009 stabilized cwd. If it happens, just send another message — the daemon retries once without `--resume`, and the agent picks up from `forge_messages` history.

---

## 12. What's deliberately not in this doc

- How to write agent system prompts that work well (separate guide, coming).
- The full ADR series (`docs/architecture_decision_record.md`).
- The Conductor scheduling cadence (it's currently manual — you click Run on tasks the Conductor spawned).
- Gated transitions / column-bound workflows / templates — that epic is in flight.

Welcome to Agentira.
