from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .base import Runtime, derive_session_handle as _derive_session_handle

logger = logging.getLogger("agentira.runtime.openclaw")

_DEFAULT_STATE_DIR = Path.home() / ".openclaw"
_DEFAULT_PORT = 18789

# Generic runner-agent that Agentira routes ALL its OpenClaw chats through.
# Per the runtime architecture: Agentira owns the agent (persona,
# system_prompt, conversation history) and OpenClaw owns the engine
# (MCP tools, workspace, code execution). The runner has bootstrap=null
# and contextInjection=never so it doesn't inject identity-shaping
# content that would fight Agentira's system_prompt.
_RUNNER_AGENT_ID = "agentira-runner"


class OpenClawRuntime(Runtime):
    provider = "openclaw"
    default_binary = "openclaw"
    env_path_override = "AGENTIRA_OPENCLAW_PATH"
    version_args = ("--version",)
    # ADR 009 / Runtime Adapter contract: OpenClaw uses its native WS RPC
    # protocol (chat.send / sessions.* + event stream) for execution.
    # We target the clean "agentira-runner" placeholder agent (created by
    # ensure_runner_agent) so that:
    #   - OpenClaw supplies the full engine (tools, workspace, MCP servers
    #     registered into its config, execution environment).
    #   - Agentira layers its own system_prompt, conversation history (via
    #     sessionKey continuity + prompt construction), per-agent MCPs
    #     (registered fresh before each dispatch), and config on top.
    # This prevents user's personal OpenClaw agent configs / personas /
    # settings from polluting Agentira agents. The runner has empty
    # systemPromptOverride and full tools profile.
    #
    # Native WS gives us incremental streaming events (text deltas, tool
    # lifecycle) instead of a single non-streaming /v1/chat/completions
    # response. Capabilities reflect the native contract.
    capabilities = ("stream_events", "resume")

    @classmethod
    def derive_session_handle(cls, *, agent_id: str, scope_key: str) -> str:
        """OpenClaw `sessionKey` for (agent, scope_key) — one server-side
        thread per Agentira conversation scope under the runner agent.
        Stable: same scope -> same key -> same thread (with KV cache
        warm)."""
        return _derive_session_handle(agent_id=agent_id, scope_key=scope_key)

    @classmethod
    def introspect(cls, binary_path: str) -> dict:
        """Read openclaw.json to extract gateway URL, token, and available models."""
        state_dir = Path(os.environ.get("OPENCLAW_STATE_DIR", str(_DEFAULT_STATE_DIR)))
        config_path = state_dir / "openclaw.json"
        if not config_path.exists():
            return {}
        try:
            cfg = json.loads(config_path.read_text())
        except Exception:
            return {}

        gw = cfg.get("gateway", {})
        port = gw.get("port", _DEFAULT_PORT)
        bind = gw.get("bind", "loopback")
        host = "127.0.0.1" if bind in ("loopback", "localhost") else "0.0.0.0"
        gateway_url = f"http://{host}:{port}"

        auth = gw.get("auth", {})
        gateway_token = auth.get("token", "") if auth.get("mode") == "token" else ""

        # Gather all model ids from providers
        models: list[str] = []
        providers = cfg.get("models", {}).get("providers", {})
        for provider_cfg in providers.values():
            for m in provider_cfg.get("models", []):
                mid = m.get("id")
                if mid:
                    # Prefix with provider name so it's unambiguous
                    pname = provider_cfg.get("api") or list(providers.keys())[0]
                    models.append(f"{pname}/{mid}")

        # Default model
        default = (cfg.get("agents", {})
                     .get("defaults", {})
                     .get("model", {})
                     .get("primary", ""))
        if default and default not in models:
            models.insert(0, default)

        return {
            "gateway_url": gateway_url,
            "gateway_token": gateway_token,
            "models": models,
            # OpenClaw now prefers native WS RPC for streaming execution
            # (chat.send + event stream) rather than the HTTP completions shim.
            "native_ws": True,
        }


def ensure_runner_agent(default_model: str = "", binary_path: str = "openclaw") -> bool:
    """Idempotently add the `agentira-runner` agent to OpenClaw's config.

    Why: Agentira owns the agent layer (persona, system_prompt, conversation
    history). OpenClaw owns the engine layer (MCP tools, workspace, code
    execution). To get the latter without the former, we route every Agentira
    chat through ONE generic OpenClaw agent whose `systemPromptOverride` is
    empty (so OpenClaw doesn't inject identity-shaping content) and whose
    `tools.profile` is "full" (so all OpenClaw-side tools are available).

    Persona is supplied by Agentira via the system message in the chat body.

    Implementation note: we MUST use the `openclaw` CLI rather than mutating
    `~/.openclaw/openclaw.json` directly. The OpenClaw gateway holds the
    config in memory and rewrites the file on its own schedule, so direct
    edits get clobbered. The CLI is the supported mutation path and the
    gateway picks up changes after a restart.

    Returns True if the entry was created, False if already present or if
    OpenClaw isn't installed/usable.
    """
    import subprocess

    # Probe whether the runner agent already exists.
    try:
        result = subprocess.run(
            [binary_path, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("openclaw CLI not available: %s", exc)
        return False
    if result.returncode != 0:
        logger.warning("openclaw agents list failed: %s", result.stderr.strip())
        return False
    try:
        agents = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("openclaw agents list returned non-JSON")
        return False

    if any(isinstance(a, dict) and a.get("id") == _RUNNER_AGENT_ID for a in agents):
        logger.debug("runner-agent %s already present", _RUNNER_AGENT_ID)
        return False

    # Pick a model: caller's hint, else the existing default agent's model.
    # If we can't determine one, let `openclaw agents add` use its own default.
    model = default_model
    if not model and agents:
        model = next((a.get("model") for a in agents if a.get("isDefault")), "") or ""
    if not model and agents:
        model = agents[0].get("model", "")

    cmd = [binary_path, "agents", "add", _RUNNER_AGENT_ID, "--non-interactive", "--json"]
    if model:
        cmd += ["--model", model]
    # Reuse the default workspace so we don't create a separate filesystem
    # tree just for the runner. The runner is shared across all Agentira
    # agents — they're distinguished by Agentira's system message, not by
    # workspace.
    if agents:
        default_ws = next((a.get("workspace") for a in agents if a.get("isDefault")), "") or ""
        if default_ws:
            cmd += ["--workspace", default_ws]

    try:
        add_result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("openclaw agents add timed out")
        return False
    if add_result.returncode != 0:
        logger.warning("openclaw agents add failed: %s", add_result.stderr.strip())
        return False

    logger.info("added %s runner-agent (model=%s)", _RUNNER_AGENT_ID, model or "<default>")

    # Now configure the runner: empty systemPromptOverride (no identity
    # injection) + tools.profile=full (all engine tools available).
    # We need the runner's index in agents.list — reload to find it.
    try:
        list2 = subprocess.run(
            [binary_path, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if list2.returncode == 0:
            updated = json.loads(list2.stdout)
            idx = next(
                (i for i, a in enumerate(updated)
                 if isinstance(a, dict) and a.get("id") == _RUNNER_AGENT_ID),
                -1,
            )
            if idx >= 0:
                for path, value in [
                    (f"agents.list[{idx}].systemPromptOverride", ""),
                    (f"agents.list[{idx}].tools", '{"profile":"full"}'),
                ]:
                    sub = subprocess.run(
                        [binary_path, "config", "set", path, value],
                        capture_output=True, text=True, timeout=10,
                    )
                    if sub.returncode != 0:
                        logger.debug("openclaw config set %s failed: %s",
                                     path, sub.stderr.strip())
    except Exception as exc:
        logger.debug("post-add configuration of runner failed (non-fatal): %s", exc)

    return True


# Names of the MCP servers Agentira registers into OpenClaw. Kept here so
# `unset` / re-register operations target exactly Agentira's entries and
# leave the user's own MCP servers alone.
_AGENTIRA_MCP_NAMES = ("agentira", "memory", "agentira-project")


def register_agentira_mcps(mcp_config: dict, *, binary_path: str = "openclaw") -> dict:
    """Register Agentira's MCP servers into OpenClaw's config (AP-103).

    We register into the runner agent's effective environment (via global
    mcp set before dispatch) because neither the old HTTP completions nor
    the native chat.send path take per-call MCP config. This keeps
    Agentira MCPs (with per-agent token + memory) on top of the clean runner
    without affecting the user's own OpenClaw agents.
    `openclaw mcp set` is the supported way.

    `mcp_config` is the `{"mcpServers": {name: {...}}}` dict produced by
    `backend.forge.mcp_registry.build_mcp_config` — it is built
    PER-AGENT (the `agentira` server's Bearer token is that agent's own
    api_key, `memory`'s MEMORY_FILE_PATH is that agent's per-project
    path). Each entry is written verbatim — OpenClaw accepts both stdio
    (`command`/`args`/`env`) and http (`type`/`url`/`headers`) shapes.

    Per-agent identity is preserved because the daemon calls this
    immediately before every OpenClaw dispatch (see
    `core.py::_execute` gateway branch): the global MCP slot is
    overwritten with THIS agent's config each time, so the runner picks
    up the right token + memory path for the dispatch it's about to
    serve. Agentira owns the agent layer; the single `agentira-runner`
    is just the engine placeholder.

    Returns {"registered": [...], "failed": [...]}.
    """
    import subprocess

    servers = (mcp_config or {}).get("mcpServers") or {}
    registered: list[str] = []
    failed: list[dict] = []

    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        try:
            result = subprocess.run(
                [binary_path, "mcp", "set", name, json.dumps(entry)],
                capture_output=True, text=True, timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            failed.append({"name": name, "error": str(exc)})
            continue
        if result.returncode == 0:
            registered.append(name)
            logger.info("Registered MCP server '%s' into OpenClaw config", name)
        else:
            failed.append({"name": name, "error": result.stderr.strip()})
            logger.warning("openclaw mcp set %s failed: %s", name, result.stderr.strip())

    return {"registered": registered, "failed": failed}
