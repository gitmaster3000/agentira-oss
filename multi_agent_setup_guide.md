# ZeroClaw Multi-Agent Setup Guide

How to create a team of AI agents, register them in Agentira, and put them to work autonomously.

---

## Big Picture

```
You need 3 things running:

  1. Agentira Backend (port 8111)  — task management   ✅ you have this
  2. ZeroClaw Agent(s)             — AI brains          ❌ install this
  3. Agentira Daemon               — polling bridge      ✅ just built this
```

The **ZeroClaw agent** is a Rust binary that runs on your machine. It's the AI brain — it has terminal access, file access, and an LLM connection. The **daemon** we built tells ZeroClaw *what* to work on by polling Agentira.

ZeroClaw is trait-driven and modular. Its key subsystems are: `agent/` (orchestration loop), `providers/` (LLM connections), `channels/` (Telegram/Discord/Slack), `tools/` (shell/file/browser execution), `memory/` (markdown/sqlite backends), `security/` (policy, pairing, secrets), and `gateway/` (webhook server). You don't need to know the internals to run it — but it helps to know where things live if something breaks.

> **Security note:** ZeroClaw's tools can execute shell commands and access files with real-world side effects. Keep agent workspaces isolated and never commit API keys or tokens to any config file.

---

## Step 1: Install Prerequisites

### 1a. Install Rust (you don't have it yet)

```powershell
# Download and run the Rust installer for Windows
winget install Rustlang.Rustup

# Or manually: go to https://rustup.rs and download rustup-init.exe
# After install, restart your terminal then verify:
rustc -V
cargo -V
```

### 1b. Verify Python deps

```powershell
# Already done, but just in case:
pip install zeroclaw httpx pydantic-settings
```

---

## Step 2: Install ZeroClaw

### 2a. Pre-built binary (recommended for Windows)

Download the latest Windows binary from the [ZeroClaw releases page](https://github.com/zeroclaw-labs/zeroclaw/releases):

```powershell
# Download v0.1.7 Windows binary (6.7 MB)
curl -L -o "$env:USERPROFILE\zeroclaw-windows.zip" `
  "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v0.1.7/zeroclaw-x86_64-pc-windows-msvc.zip"

# Extract
Expand-Archive "$env:USERPROFILE\zeroclaw-windows.zip" -DestinationPath "$env:USERPROFILE\zeroclaw-bin" -Force

# Copy to cargo bin (already on PATH)
Copy-Item "$env:USERPROFILE\zeroclaw-bin\zeroclaw.exe" "$env:USERPROFILE\.cargo\bin\zeroclaw.exe"

# Verify
zeroclaw --version
```

### 2b. Build from source (alternative)

> [!WARNING]
> **Windows + Git Bash gotcha:** The MSVC Rust toolchain uses `link.exe`, but Git Bash puts its own `/usr/bin/link` (GNU tool) first on PATH, causing linker failures. If you hit `error: linking with link.exe failed`, either install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with the "C++ build tools" workload, or use the pre-built binary above.

```powershell
# Clone the ZeroClaw repository
cd ~
git clone https://github.com/zeroclaw-labs/zeroclaw.git
cd zeroclaw

# Build in release mode (takes 2-5 minutes first time)
cargo build --release

# Install the binary globally
cargo install --path .

# Verify
zeroclaw --version
```

---

## Step 3: Create Your Agent Team in Agentira

Before setting up ZeroClaw, create bot profiles in Agentira so each agent has its own identity and API key.

### 3a. Create bot profiles

You can do this via the Agentira UI (Settings → Service Accounts) or via the REST API:

```powershell
# Create 3 bot profiles — each gets a unique API key
$base = "http://127.0.0.1:8111"

# Architect Bot
Invoke-RestMethod -Method POST "$base/api/service-accounts" `
  -ContentType "application/json" `
  -Body '{"name": "arch-bot"}'

# Backend Bot  
Invoke-RestMethod -Method POST "$base/api/service-accounts" `
  -ContentType "application/json" `
  -Body '{"name": "backend-bot"}'

# Frontend Bot
Invoke-RestMethod -Method POST "$base/api/service-accounts" `
  -ContentType "application/json" `
  -Body '{"name": "frontend-bot"}'
```

**Save the API keys** returned — you'll need them for the daemon.

### 3b. Add bots to your project

```powershell
$project_id = "7b4232d3e521"  # Agentira Platform project

# Add each bot as a project member
Invoke-RestMethod -Method POST "$base/api/projects/$project_id/members" `
  -ContentType "application/json" `
  -Body '{"profile_name": "arch-bot"}'

Invoke-RestMethod -Method POST "$base/api/projects/$project_id/members" `
  -ContentType "application/json" `
  -Body '{"profile_name": "backend-bot"}'

Invoke-RestMethod -Method POST "$base/api/projects/$project_id/members" `
  -ContentType "application/json" `
  -Body '{"profile_name": "frontend-bot"}'
```

### 3c. Verify

```powershell
# List all service accounts to see their IDs and API keys
Invoke-RestMethod "$base/api/service-accounts"
```

---

## Step 4: Set Up ZeroClaw Agent Workspaces

Each agent gets its **own workspace directory** with its own config.

### 4a. Create workspace directories

```powershell
$agentsDir = "$env:USERPROFILE\.zeroclaw-agents"
mkdir "$agentsDir\arch-bot" -Force
mkdir "$agentsDir\backend-bot" -Force
mkdir "$agentsDir\frontend-bot" -Force
```

### 4b. Onboard each agent

ZeroClaw's `onboard` command creates the config. You need an **LLM provider API key** (pick one):

| Provider | Get key at |
|---|---|
| **OpenRouter** (recommended — access to all models) | [openrouter.ai/keys](https://openrouter.ai/keys) |
| **OpenAI** | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| **Anthropic** | [console.anthropic.com](https://console.anthropic.com) |
| **Google Gemini** | [aistudio.google.com](https://aistudio.google.com) |
| **Ollama** (free, local) | [ollama.com](https://ollama.com) — no key needed |

```powershell
# Onboard each agent with your chosen provider
# Example using OpenRouter:

$env:ZEROCLAW_WORKSPACE = "$agentsDir\arch-bot"
zeroclaw onboard --quick --provider openrouter --api-key "sk-or-v1-YOUR_KEY"

$env:ZEROCLAW_WORKSPACE = "$agentsDir\backend-bot"
zeroclaw onboard --quick --provider openrouter --api-key "sk-or-v1-YOUR_KEY"

$env:ZEROCLAW_WORKSPACE = "$agentsDir\frontend-bot"
zeroclaw onboard --quick --provider openrouter --api-key "sk-or-v1-YOUR_KEY"
```

> [!TIP]
> **Free option with Ollama:** Install Ollama, pull a model (`ollama pull llama3`), then use `--provider ollama` with no API key needed. Great for testing.

### 4c. Configure MCP connection to Agentira

Each agent needs to know about Agentira's MCP server. Edit each agent's `config.toml`:

```powershell
# Example: edit arch-bot's config
notepad "$agentsDir\arch-bot\config.toml"
```

Add this MCP server section (use the API key from step 3a):

```toml
[mcp.servers.agentira]
transport = "http"
url = "http://127.0.0.1:8000/mcp"

[mcp.servers.agentira.headers]
Authorization = "Bearer <ARCH-BOT-API-KEY-FROM-STEP-3>"
```

Do this for all 3 agents with their respective API keys.

> [!WARNING]
> Never commit `config.toml` files containing real API keys to version control. Use environment variables or a secrets manager for production setups.

For the full config schema and all available options, see [`docs/config-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/config-reference.md) and [`docs/commands-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/commands-reference.md) in the ZeroClaw repo.

---

## Step 5: Start Everything

You'll need **4 terminals** open:

### Terminal 1: Agentira Backend
```powershell
cd c:\agentira
python run.py
# Running on http://0.0.0.0:8111
```

### Terminal 2: Agentira MCP Server
```powershell
cd c:\agentira
python -m backend.mcp_server
# Running on http://127.0.0.1:8000
```

### Terminal 3: ZeroClaw Agents (one per bot, or use daemon mode)
```powershell
# Start arch-bot
$env:ZEROCLAW_WORKSPACE = "$env:USERPROFILE\.zeroclaw-agents\arch-bot"
zeroclaw daemon --port 3001

# In another terminal: backend-bot
$env:ZEROCLAW_WORKSPACE = "$env:USERPROFILE\.zeroclaw-agents\backend-bot"
zeroclaw daemon --port 3002

# In another terminal: frontend-bot
$env:ZEROCLAW_WORKSPACE = "$env:USERPROFILE\.zeroclaw-agents\frontend-bot"
zeroclaw daemon --port 3003
```

### Terminal 4+: Agentira Daemons (one per bot)
```powershell
# Daemon for arch-bot
python -m agents.daemon --bot-name arch-bot --api-key <ARCH-BOT-AGENTIRA-KEY>

# Daemon for backend-bot (separate terminal)
python -m agents.daemon --bot-name backend-bot --api-key <BACKEND-BOT-AGENTIRA-KEY>

# Daemon for frontend-bot (separate terminal)
python -m agents.daemon --bot-name frontend-bot --api-key <FRONTEND-BOT-AGENTIRA-KEY>
```

---

## Step 6: Assign Tasks and Watch

Now go to the Agentira UI and:

1. **Create tasks** in the Agentira Platform project
2. **Assign** them to `arch-bot`, `backend-bot`, or `frontend-bot`
3. **Move** them to [todo](file:///c:/agentira/tests/test_daemon.py#118-127) status
4. **Wait** — the daemon polls every 2 minutes, picks up the task, sends it to ZeroClaw, and reports back

Check the task's activity feed in Agentira to see the agent's progress and results.

---

## Quick Reference

| Component | Port | What it does |
|---|---|---|
| Agentira REST API | 8111 | Task CRUD, profiles, notifications |
| Agentira MCP Server | 8000 | Tool access for agents (MCP protocol) |
| ZeroClaw arch-bot | 3001 | AI agent runtime + dashboard |
| ZeroClaw backend-bot | 3002 | AI agent runtime + dashboard |
| ZeroClaw frontend-bot | 3003 | AI agent runtime + dashboard |

### Agent Dashboards

Each ZeroClaw daemon exposes a web dashboard at its port:
- `http://localhost:3001` — arch-bot dashboard (AgentChat, Cron, Memory, Cost)
- `http://localhost:3002` — backend-bot dashboard
- `http://localhost:3003` — frontend-bot dashboard

---

## ZeroClaw Further Reading

| Doc | What it covers |
|---|---|
| [`docs/commands-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/commands-reference.md) | All CLI commands and flags |
| [`docs/config-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/config-reference.md) | Full config schema |
| [`docs/providers-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/providers-reference.md) | LLM provider options |
| [`docs/channels-reference.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/channels-reference.md) | Telegram, Discord, Slack setup |
| [`docs/troubleshooting.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/troubleshooting.md) | Common issues and fixes |
| [`docs/one-click-bootstrap.md`](https://github.com/zeroclaw-labs/zeroclaw/blob/main/docs/one-click-bootstrap.md) | Bootstrap script alternative |

---

## Quickstart (Minimal — One Agent, Dry Run)

If you just want to test the daemon without ZeroClaw installed:

```powershell
# 1. Start Agentira backend
cd c:\agentira
python run.py

# 2. Create a task assigned to "antigravity" with status "todo"
#    (use the Agentira UI or REST API)

# 3. Run daemon in dry-run mode
python -m agents.daemon `
  --bot-name antigravity `
  --api-key 44f736d1c07ac684d8eb8aa464995a092e85d5ead974ba598d7b9fa4ee9110ea `
  --dry-run
```

This will poll for tasks and log what it *would* do, without needing ZeroClaw.
