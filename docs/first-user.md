# First user — your 10-minute start

Welcome. This is the doc to read when someone just gave you a URL like `https://agentira.up.railway.app` and said "go sign up."

Follow it top to bottom. You'll have agents working on real code by minute 12.

---

## What you're signing up for

Agentira is a self-hosted platform for running AI coding agents on real software projects. You won't be talking to a model — you'll be running a small team of agents (Conductor, Planner, two Implementers, Reviewer, DevOps) against your repos. They edit code on **your machine** while the workspace coordinates them.

**Two pieces:**

1. **The website** — runs in the cloud, hosted by whoever gave you the URL. Where you sign in, create projects, drop briefs, hit Run.
2. **The daemon** — a small program you install **on your own Mac/PC**. Bridges the cloud workspace to your local `claude` CLI. The actual code editing happens here.

You need both. The cloud alone can't touch your code; the daemon alone has no UI.

---

## Step 1 — Sign up (2 minutes)

1. Open the URL the operator gave you (something like `https://agentira.up.railway.app`).
2. Hit **Sign up**.
3. Pick a username + password. Or click "Continue with Google / GitHub" if the operator wired OAuth.
4. You're in. You land on Flowty Studio (the workspace + board).

On the left sidebar you'll already see:
- **Projects** (empty for now)
- **Agents** under Forge — 6 agents pre-seeded: Conductor, Planner, Backend Implementer, Frontend Implementer, Reviewer, DevOps.

Don't create a project yet. Daemon first.

---

## Step 2 — Grab your API key (30 seconds)

1. Click your avatar (top right) → **Settings** → **API key**.
2. Click "Reveal" → copy the long hex string.
3. Keep it in your clipboard for the next step.

> The key is your identity to the daemon AND to any MCP client (Cursor, Claude Desktop, etc.) you point at this workspace. Treat it like a password. You can rotate it later from the same screen.

---

## Step 3 — Install the daemon (5 minutes)

### Prerequisites you need locally

- **Python 3.11 or newer** (`python3 --version` to check; install from [python.org](https://www.python.org/downloads/) if missing)
- **Claude CLI** (`claude --version` to check; install with `npm install -g @anthropic-ai/claude-code` if missing)
- **Git** (almost certainly already installed)

### Run the installer

#### Mac / Linux

Replace `YOUR-INSTANCE` with the same URL you signed up at (e.g. `https://agentira.up.railway.app`):

```bash
curl -fsSL https://YOUR-INSTANCE/api/public/install.sh | bash
```

#### Windows (PowerShell as Administrator)

```powershell
iwr -useb https://YOUR-INSTANCE/api/public/install.ps1 | iex
```

The script will:

1. Check Python + Claude are present (refuses to continue with a clear error if not).
2. Ask for your **backend URL**, then `pip install` the agentira-cli wheel from that instance.
3. Ask for your **API key** (from Step 2) and write `~/.agentira/.env`.
4. Print the command to start the daemon.

Upgrade later: `agentira daemon update` (pulls the latest wheel from the same instance).

### Start the daemon

```bash
agentira daemon
```

You should see, within ~2 seconds:

```
✓ Config loaded: api_url=https://agentira.up.railway.app
✓ Found runtime: claude (/usr/local/bin/claude, claude-code 2.x)
✓ WS connected: wss://agentira.up.railway.app/api/forge/daemon/ws
✓ Registered daemon abc12345 (1 runtime)
Daemon ready. Press Ctrl+C to stop.
```

**Leave that terminal open.** The daemon keeps running while you use the app. (When you close the terminal, the daemon stops — see "Keeping the daemon running" below for tmux / launchd / Windows-service setups.)

### Verify the connection from the web UI

Go back to the browser, click **Forge → Agents**. Each of the 6 default agents should now show a **green dot** next to its name (meaning it has a bound runtime — your daemon). If you still see grey dots, click any agent → **Runtime** → select the one your daemon registered.

---

## Step 4 — Create your first project (1 minute)

1. Click **+ New Project** in the Studio sidebar.
2. The wizard opens. Four steps:

   **Basics** — Name (e.g. "Side project"), category, description.

   **Attachments** — Drag in any briefs, designs, brand guides. Markdown, PDF, images, even zips of design files. The agents will read these.

   **Initial tasks** — Pre-filled with a "Plan this project" task. Leave it as-is or tweak. You can add more rows here for tasks you already know you need (e.g. "Set up CI/CD", "Bootstrap the database schema").

   **Agents** — Conductor pre-checked. Add the other agents you want on this project (Backend Implementer, Frontend Implementer if your project's a full-stack thing, etc.).

3. Click **Create**.

You land on the project's dashboard. The "Plan this project" task is in the `todo` column, assigned to the Conductor.

---

## Step 5 — Hit Run (the magic moment)

1. Click the "Plan this project" task to open it.
2. Click the big **Run** button.
3. The Run page opens. Watch the conversation stream live:

   - The Conductor reads your project description + attachments.
   - It picks a tech stack with justification.
   - It writes a one-page plan, registers it as a `report` artifact (clickable on the right side of the run page).
   - It creates 3-8 child tasks via the MCP tools, each with a clear definition of done.
   - It calls `finish_run` with `outcome: succeeded`.

4. Go back to the board. You'll see 3-8 new tasks in `backlog`. Open them — the Conductor has filled in titles, descriptions, priorities, and DoDs.

---

## Step 6 — Assign + run the real work

1. Open one of the new tasks (say, a backend one).
2. Change the **Assignee** to **Backend Implementer**.
3. Click **Run**.

The Backend Implementer:
- Lands in its own git worktree at `~/.agentira/agents/<id>/home/repos/<project>/task-<id>/`.
- Reads the task description + DoD.
- Edits files in **your real repo** (the one you configured in Project Settings, or a fresh clone if you haven't).
- Commits to a branch named `agent/<id>/task/<id>`.
- Opens a PR (if you've wired GitHub access).
- Registers the PR as an artifact.
- Calls `finish_run`.

You see the diff, the conversation, and the artifacts live on the Run page. **Don't close the daemon terminal.**

---

## What to do next

- **Comment on a task to steer it.** Mid-run comments pause the agent, capture the session, and resume with your message as the next turn. Same run, same context.
- **Review what the agent did.** Hit the diff tab on the Run page. Click the PR artifact to see it on GitHub.
- **Hit Restart** on a terminal run to retry with a context hint. Useful when you change your mind or the first attempt missed something.
- **Edit any agent's prompt.** Forge → Agents → click → System prompt. The defaults are good; tune them to your codebase's conventions.

---

## Keeping the daemon running

The daemon stops when you close its terminal. For longer-running setups:

### Mac — launchd (auto-start on login)

```bash
agentira daemon install-service
```

This creates `~/Library/LaunchAgents/com.agentira.daemon.plist` and starts it. The daemon now boots when you log in. Stop it with `launchctl unload ~/Library/LaunchAgents/com.agentira.daemon.plist`.

### Linux — systemd user service

```bash
agentira daemon install-service --systemd
```

### Windows — Task Scheduler

```powershell
agentira daemon install-service
```

### Quick + dirty — tmux

```bash
tmux new -s agentira 'agentira daemon'
# Detach with Ctrl-b d; reattach with: tmux attach -t agentira
```

---

## Troubleshooting

| What you see | What's wrong | Fix |
|---|---|---|
| `claude: command not found` during install | Claude CLI missing | `npm install -g @anthropic-ai/claude-code` |
| `python3: command not found` | Python missing | Install from [python.org](https://www.python.org/downloads/) — 3.11 or newer |
| `WS connection refused` | Backend URL wrong, or backend down | Re-check the URL in `~/.agentira/.env`; verify the website itself loads in your browser |
| `401 Unauthorized` | API key wrong or rotated | Copy a fresh key from Settings → API key, update `~/.agentira/.env` |
| Agents still show grey dots in Forge → Agents | Daemon connected but didn't auto-bind | Click an agent → Runtime dropdown → pick the one your daemon registered |
| Run starts but agent says "no claude found" | The daemon registered, but the claude binary moved | Restart the daemon (Ctrl-C then `agentira daemon`); it re-detects runtimes |
| Diff is empty after a run | Agent worked but didn't commit, OR worked outside the worktree | Open the Run page → "Workdir (cwd)" diagnostic → `cd` there to inspect |
| Browser shows "Failed to fetch" on every API call | Frontend's nginx isn't proxying correctly. **This is an operator problem** — tell whoever gave you the URL | (operator: check `agentira-frontend/nginx.conf` `proxy_pass`) |

---

## Privacy + what stays local

- **Your code** — never leaves your machine. The agents edit files at `~/.agentira/agents/...` on **your** disk. The cloud workspace stores task metadata (titles, descriptions, statuses, diffs that the daemon chooses to upload) but never the working tree itself.
- **Conversation transcripts** — stored in the workspace's database so you can scroll the chat history. If you don't want them in the cloud, host your own instance (the operator's deployment is yours; see [deployment.md](deployment.md)).
- **Attachments** — uploaded to the workspace, stored in its database/volume. Anyone in the project sees them.
- **API key** — only on your machine (in `~/.agentira/.env`) and on the workspace's DB. Treat it like a password.

---

## When something breaks and you want to send a bug report

Include:
- The URL you signed up at.
- Approximately when (so the operator can grep logs).
- What you were doing (which task, which agent, what you clicked).
- The Run ID (from the Run page URL) if a specific run misbehaved.
- The last 50 lines of the daemon's terminal output.

That's usually enough for the operator to diagnose without screen-shares.

---

## Glossary

- **Workspace** — your account's slice of the platform. Everything you create lives here.
- **Project** — a Kanban board for one effort (one product, one repo, one initiative). Has attachments, conventions, member agents.
- **Task** — a Kanban card. Has a title, description, DoD, assignee.
- **Run** — one work episode an agent did on a task. Has a verdict (succeeded / blocked / failed / needs_input), a diff, artifacts, a transcript.
- **Turn** — one dispatch within a run (or a free chat that didn't crystallize into a run). Single back-and-forth with the agent.
- **Conversation** — the agent's memory across many turns for one scope (task or general chat).
- **Artifact** — a deliverable an agent registered during a run (a PR URL, a file path, a report).
- **MCP** — Model Context Protocol — how the agents call tools (`create_task`, `register_run_artifact`, etc.). Don't sweat it; you won't see it directly.
- **Conductor** — the workspace orchestrator agent. Plans the queue, assigns work to the best-fit agent, sends daily reports.

---

## Where to go from here

- [Full Getting Started](getting-started.md) — the same walkthrough plus deeper sections on Conversations, work-signals, the verified state machine, and the autonomy story.
- [Architecture](architecture.md) — if you want to understand what's happening under the hood.
- [Deployment](deployment.md) — for if you become the operator (self-hosting your own instance).
- The Agent prompts under **Forge → Agents** — the defaults are tuned but you'll want to add your conventions ("Always use ruff", "All commits squash-merge", etc.).

Have fun. The whole point of this thing is the moment you walk away from the screen and come back to a board full of work the agents did while you were gone.
