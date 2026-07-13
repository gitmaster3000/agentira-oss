from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .base import Runtime, TurnRequest
from .openclaw_engine import (
    clear_engine_session,
    derive_engine_session_key,
    ensure_engine_agent,
    normalize_session_key,
)

logger = logging.getLogger("agentira.runtime.openclaw")

_DEFAULT_STATE_DIR = Path.home() / ".openclaw"
_DEFAULT_PORT = 18789

# Legacy shared placeholder — kept only so older docs/tests/daemon boot
# that still call ensure_runner_agent do not crash. Execution no longer
# routes through this id; each Agentira agent gets ar-<agent8>.
_RUNNER_AGENT_ID = "agentira-runner"


class OpenClawRuntime(Runtime):
    provider = "openclaw"
    default_binary = "openclaw"
    env_path_override = "AGENTIRA_OPENCLAW_PATH"
    version_args = ("--version",)
    # ADR 009: native WS (chat.send + event stream).
    # Ownership split:
    #   Agentira — persona, memory MCP, prompts, board tools, workdir provision
    #   OpenClaw — tool engine only (read/edit/exec + host plugins)
    # One OpenClaw engine agent per Agentira agent (ar-<agent8>), workspace
    # bound to the Agentira-provisioned desk, sessionKey routes to that
    # engine so we never land on the user's personal main agent.
    capabilities = ("stream_events", "resume")

    @classmethod
    def derive_session_handle(cls, *, agent_id: str, scope_key: str) -> str:
        """OpenClaw sessionKey: agent:ar-<id>:<scope> (routes to engine agent)."""
        return derive_engine_session_key(agent_id=agent_id, scope_key=scope_key)

    @classmethod
    def clear_handle(cls, *, agent_id: str, scope_key: str) -> None:
        """Drop OpenClaw-side thread; backend also clears runtime_session_id."""
        key = derive_engine_session_key(agent_id=agent_id, scope_key=scope_key)
        clear_engine_session(key)

    @classmethod
    async def execute_turn(cls, req: TurnRequest):
        """Native OpenClaw WS path: engine agent + workdir bind + chat.send."""
        from agentira_cli.runtimes.openclaw_ws import run_openclaw_ws
        from agentira_cli.runtimes.openclaw_device import (
            RegistrationError,
            RegistrationPendingError,
            ensure_registered,
        )

        # Ensure 1:1 engine agent + bind workspace to Agentira desk (once
        # when desk changes — cached). Persona stays empty on OC side.
        try:
            ensure_engine_agent(
                req.agent_id,
                workdir=req.workdir or "",
                default_model=req.model or "",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ensure_engine_agent failed trace=%s: %s", req.trace_id, exc,
            )

        # Register Agentira MCPs so THIS agent's token + memory are visible.
        if req.mcp_config_json:
            try:
                reg = register_agentira_mcps(json.loads(req.mcp_config_json))
                if reg.get("failed"):
                    logger.warning("MCP register (openclaw) partial: %s", reg["failed"])
            except Exception as exc:
                logger.warning(
                    "MCP register (openclaw) failed trace=%s: %s",
                    req.trace_id, exc,
                )

        # Resume id may be legacy agentira:… — normalize to agent:ar-… form.
        session_key = normalize_session_key(
            req.resume_session_id or "",
            agent_id=req.agent_id,
            scope_key=req.scope_key,
        )
        if not session_key:
            try:
                session_key = cls.derive_session_handle(
                    agent_id=req.agent_id, scope_key=req.scope_key,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "derive_session_handle failed trace=%s: %s",
                    req.trace_id, exc,
                )

        # pid=0 inflight so heartbeats keep the scope live for the WS turn.
        if req.scope_key:
            try:
                from agentira_cli.daemon import inflight as _inflight_reg
                _inflight_reg.record(
                    scope_key=req.scope_key,
                    trace_id=req.trace_id,
                    run_id=req.run_id,
                    pid=0,
                    daemon_id=req.daemon_id,
                    env_teardown=req.env_teardown,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "inflight record (openclaw ws) skipped trace=%s: %s",
                    req.trace_id, exc,
                )

        try:
            device_identity = ensure_registered(
                gateway_url=req.gateway_url,
                gateway_token=req.gateway_token,
            )
        except RegistrationPendingError as exc:
            logger.error(
                "openclaw device pairing pending trace=%s: %s",
                req.trace_id, exc,
            )
            raise RuntimeError(str(exc)) from exc
        except RegistrationError as exc:
            logger.error(
                "openclaw device registration failed trace=%s: %s",
                req.trace_id, exc,
            )
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            logger.error(
                "openclaw device registration error trace=%s: %s",
                req.trace_id, exc,
            )
            raise RuntimeError(
                f"OpenClaw device registration failed: {exc}. "
                "Run: agentira daemon pair"
            ) from exc

        return await run_openclaw_ws(
            req.gateway_url,
            req.gateway_token,
            req.agent_name,
            req.prompt,
            model=req.model,
            system_prompt=req.system_prompt,
            on_event=req.on_event,
            session_key=session_key,
            resume_session_id=session_key if req.resume_session_id else "",
            workdir=req.workdir or "",
            stdout_log_path=req.stdout_log_path or None,
            stderr_log_path=req.stderr_log_path or None,
            trace_id=req.trace_id,
            device_identity=device_identity,
        )

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


def _configure_runner(binary_path: str, agents: list) -> None:
    """Apply the runner contract: empty systemPromptOverride + tools.profile=full."""
    import subprocess

    idx = next(
        (i for i, a in enumerate(agents)
         if isinstance(a, dict) and a.get("id") == _RUNNER_AGENT_ID),
        -1,
    )
    if idx < 0:
        return
    for path, value in [
        (f"agents.list[{idx}].systemPromptOverride", ""),
        (f"agents.list[{idx}].tools", '{"profile":"full"}'),
    ]:
        try:
            sub = subprocess.run(
                [binary_path, "config", "set", path, value],
                capture_output=True, text=True, timeout=10,
            )
            if sub.returncode != 0:
                logger.debug("openclaw config set %s failed: %s",
                             path, sub.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.debug("openclaw config set %s timed out", path)


def ensure_runner_agent(default_model: str = "", binary_path: str = "openclaw") -> bool:
    """Legacy boot hook (daemon start). Prefer ensure_engine_agent per turn.

    Kept so older call sites do not break. Execution uses 1:1 ``ar-<id>``
    engine agents (see openclaw_engine.py); this only ensures skipBootstrap
    defaults and the legacy placeholder if present.
    """
    # Prefer global skipBootstrap so desks are not polluted with SOUL.md.
    try:
        _config_set_skip_bootstrap(binary_path)
    except Exception:  # noqa: BLE001
        pass
    return _ensure_legacy_runner(default_model=default_model, binary_path=binary_path)


def _config_set_skip_bootstrap(binary_path: str = "openclaw") -> None:
    import subprocess
    try:
        subprocess.run(
            [binary_path, "config", "set", "agents.defaults.skipBootstrap", "true"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass


def _ensure_legacy_runner(default_model: str = "", binary_path: str = "openclaw") -> bool:
    """Idempotently ensure legacy agentira-runner exists (non-execution path)."""
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
        logger.debug("runner-agent %s already present — reconfiguring", _RUNNER_AGENT_ID)
        _configure_runner(binary_path, agents)
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

    # Reload agents.list to find the runner index after add.
    try:
        list2 = subprocess.run(
            [binary_path, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if list2.returncode == 0:
            _configure_runner(binary_path, json.loads(list2.stdout))
    except Exception as exc:
        logger.debug("post-add configuration of runner failed (non-fatal): %s", exc)

    return True


# Names of the MCP servers Agentira registers into OpenClaw. Kept here so
# `unset` / re-register operations target exactly Agentira's entries and
# leave the user's own MCP servers alone.
_AGENTIRA_MCP_NAMES = ("agentira", "memory", "agentira-project")

# Last applied MCP fingerprint (process-local). Re-running `openclaw mcp set`
# on every chat turn is ~2s×N and triggers a gateway config reload that
# kills in-flight agent sessions (session file lock / bundle-mcp disposed).
_last_mcp_fingerprint: str | None = None


def _mcp_fingerprint(servers: dict) -> str:
    return json.dumps(servers, sort_keys=True, separators=(",", ":"), default=str)


def _read_openclaw_mcp_servers() -> dict:
    """Current mcp.servers from openclaw.json (empty dict if missing)."""
    state_dir = Path(os.environ.get("OPENCLAW_STATE_DIR", str(_DEFAULT_STATE_DIR)))
    config_path = state_dir / "openclaw.json"
    try:
        cfg = json.loads(config_path.read_text())
    except Exception:
        return {}
    mcp = cfg.get("mcp") or {}
    servers = mcp.get("servers") or {}
    return servers if isinstance(servers, dict) else {}


def _entry_matches(desired: dict, existing: dict | None) -> bool:
    """True if desired server config is already what OpenClaw has."""
    if not isinstance(existing, dict):
        return False
    # Compare as canonical JSON so key order / whitespace don't force a rewrite.
    return _mcp_fingerprint(desired) == _mcp_fingerprint(existing)


def register_agentira_mcps(mcp_config: dict, *, binary_path: str = "openclaw",
                           force: bool = False) -> dict:
    """Register Agentira's MCP servers into OpenClaw's config (AP-103).

    Skips `openclaw mcp set` when the desired servers already match what's
    in openclaw.json (and the in-process cache). That avoids multi-second
    CLI round-trips and gateway reloads on every chat turn — those reloads
    were racing in-flight OpenClaw sessions (session lock timeouts).

    Still rewrites when the per-agent token / memory path / server set
    changes (`force=True` always writes).

    Returns {"registered": [...], "failed": [...], "skipped": [...]} .
    """
    import subprocess
    global _last_mcp_fingerprint

    servers = (mcp_config or {}).get("mcpServers") or {}
    if not isinstance(servers, dict) or not servers:
        return {"registered": [], "failed": [], "skipped": []}

    fp = _mcp_fingerprint(servers)
    if not force and fp == _last_mcp_fingerprint:
        return {
            "registered": [],
            "failed": [],
            "skipped": list(servers.keys()),
        }

    existing = {} if force else _read_openclaw_mcp_servers()
    registered: list[str] = []
    failed: list[dict] = []
    skipped: list[str] = []

    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        if not force and _entry_matches(entry, existing.get(name)):
            skipped.append(name)
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

    # Only mark fingerprint current if nothing failed (partial write may leave
    # openclaw half-updated).
    if not failed:
        _last_mcp_fingerprint = fp
    elif registered or skipped:
        # Best-effort: next turn will re-diff against disk.
        _last_mcp_fingerprint = None

    if skipped and not registered:
        logger.debug("openclaw MCP already up to date; skipped %s", skipped)

    return {"registered": registered, "failed": failed, "skipped": skipped}
