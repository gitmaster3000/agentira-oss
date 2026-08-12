---
id: runtimes
title: Runtimes and adapters
sidebar_label: Runtimes
---

# Runtimes and adapters

A runtime is the external tool that edits code. An adapter maps Agentira's contract onto that tool's native features.

Adapters live in `agentira-cli/agentira_cli/runtimes/`.

## Supported runtimes

| Runtime | Adapter |
|---|---|
| Claude CLI | `claude.py` |
| Codex | `codex.py` |
| Grok | `grok.py` |
| Gemini | `gemini.py` |
| OpenCode | `opencode.py` |
| OpenClaw | `openclaw.py` and supporting modules |
| Ollama | `ollama.py` |

The daemon detects whichever are present on `PATH` at startup and registers them with their capabilities.

```bash
agentira runtime list
```

## Capability flags

Runtimes differ. Rather than assume a lowest common denominator, each adapter declares what it supports:

| Flag | Meaning |
|---|---|
| `resume` | Can continue a prior session |
| `stop` | Supports clean termination |
| `pause` | Supports pause distinct from stop |
| `stream_events` | Emits structured events during execution |
| `stream_json` | Emits structured JSON output |
| `tools` | Supports tool calling |
| `mcp` | Speaks MCP |
| `mcp_config` | Accepts MCP server configuration |
| `models` | Exposes a model list |
| `compact` | Supports context compaction |
| `http_gateway` | Reached over HTTP rather than as a subprocess |

Agentira degrades to the closest supported behaviour rather than failing. A runtime without `resume` starts a fresh session and replays context from stored history.

## The MCP capability matters most

:::warning
A runtime without `mcp_config` cannot call Agentira's tools.

The model may be entirely capable, but it cannot register artifacts, create tasks, or declare outcomes. Agents on such a runtime tend to *narrate* tool use as prose — they describe registering an artifact instead of registering one.

The visible symptom is a run that reports success while leaving nothing on the board.
:::

Check before assigning real work:

```bash
agentira runtime list
```

## Session continuity

Runtimes solve continuity differently. The Claude CLI resumes by session identifier; OpenClaw uses a session key. The adapter hides the difference.

What makes this work is the stable working directory per agent and task. The worktree inside is recreated per run, but the directory the runtime keys off persists.

## Configuration

Adapters read paths and model lists from the environment:

| Variable | Purpose |
|---|---|
| `AGENTIRA_CLAUDE_PATH` | Override the Claude CLI binary path |
| `AGENTIRA_CLAUDE_MODELS` | Override the advertised model list |
| `AGENTIRA_CODEX_PATH` | Override the Codex binary path |
| `AGENTIRA_CODEX_MODELS` | Override the advertised model list |
| `AGENTIRA_GEMINI_PATH` | Override the Gemini binary path |
| `AGENTIRA_GATEWAY_TIMEOUT` | Timeout for HTTP gateway runtimes |

Follow the same pattern for other adapters.

## Adding an adapter

1. Implement the contract in `agentira-cli/agentira_cli/runtimes/<name>.py`, using `base.py` as the reference.
2. Declare capability flags honestly. Claiming an unsupported capability produces worse failures than declaring the truth.
3. Register the adapter in `registry.py`, including detection.
4. Add tests. The existing adapter tests are the pattern.

Declare only what you have implemented. The resolver is built to downshift gracefully; it cannot recover from a false claim.
