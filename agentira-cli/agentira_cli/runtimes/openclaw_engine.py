"""OpenClaw engine agents — one isolated OC agent per Agentira agent.

Contract (Agentira owns agentic quality; OpenClaw is the tool engine):

- Persona / soul / memory / prompts / board tools → Agentira
- File/exec tools + host plugins → OpenClaw
- Workspace path → Agentira-provisioned desk (bound onto the engine agent)
- Session / resume id → Agentira stores; OpenClaw holds tool-thread under sessionKey
- Clear / cancel → Agentira drops runtime_session_id + sessions.reset / abort

Engine agent id: ``ar-<agent8>`` (OpenClaw-safe: ``[a-z0-9][a-z0-9_-]{0,63}``).
Session key: ``agent:ar-<agent8>:<sanitized-scope>`` so tools never route to
the user's personal ``main`` agent / default workspace.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("agentira.runtime.openclaw_engine")

_DEFAULT_STATE_DIR = Path.home() / ".openclaw"
_SCOPE_SANITIZE = re.compile(r"[^A-Za-z0-9._:\-]+")
_ENGINE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Process-local cache: engine_id -> last absolute workspace we bound.
# Avoids CLI round-trips when the desk did not change (same task, N turns).
_bound_workspace: dict[str, str] = {}


def engine_agent_id(agentira_agent_id: str) -> str:
    """Stable OpenClaw agent id for an Agentira agent."""
    raw = (agentira_agent_id or "").strip().lower()
    if not raw:
        return "ar-unknown"
    # Prefer first 8 hex/alnum chars (Agentira ids are 12-char hex).
    stem = re.sub(r"[^a-z0-9]", "", raw)[:8] or "unknown"
    eid = f"ar-{stem}"
    if not _ENGINE_ID_RE.match(eid):
        eid = "ar-" + re.sub(r"[^a-z0-9_-]", "", stem)[:8]
    return eid[:64]


def derive_engine_session_key(*, agent_id: str, scope_key: str) -> str:
    """OpenClaw sessionKey that routes to this engine agent.

    Format required by OpenClaw parseAgentSessionKey:
      agent:<engineId>:<rest>
    """
    if not agent_id or not scope_key:
        return ""
    eng = engine_agent_id(agent_id)
    scope = _SCOPE_SANITIZE.sub("_", scope_key.strip())
    if not scope:
        return ""
    return f"agent:{eng}:{scope}"


def normalize_session_key(key: str, *, agent_id: str, scope_key: str = "") -> str:
    """Upgrade legacy keys (``agentira:…``) and empty keys to engine form.

    Legacy Agentira keys were stored as ``agentira:<a8>:<scope>`` and OpenClaw
    treated them as default-agent (``main``) sessions — wrong workspace.
    """
    k = (key or "").strip()
    if k.lower().startswith("agent:"):
        return k
    # Prefer re-derive from agent+scope when available.
    if agent_id and scope_key:
        return derive_engine_session_key(agent_id=agent_id, scope_key=scope_key)
    if k.lower().startswith("agentira:"):
        parts = k.split(":", 2)
        if len(parts) >= 3 and agent_id:
            eng = engine_agent_id(agent_id)
            return f"agent:{eng}:{parts[2]}"
        if len(parts) >= 3:
            # Best-effort: use embedded agent8 from the legacy key.
            eng = engine_agent_id(parts[1])
            return f"agent:{eng}:{parts[2]}"
    if agent_id and k:
        eng = engine_agent_id(agent_id)
        return f"agent:{eng}:{_SCOPE_SANITIZE.sub('_', k)}"
    return k


def _state_dir() -> Path:
    return Path(os.environ.get("OPENCLAW_STATE_DIR", str(_DEFAULT_STATE_DIR)))


def _list_agents(binary_path: str = "openclaw") -> list[dict]:
    try:
        result = subprocess.run(
            [binary_path, "agents", "list", "--json"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("openclaw agents list unavailable: %s", exc)
        return []
    if result.returncode != 0:
        logger.warning("openclaw agents list failed: %s", result.stderr.strip())
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _config_set(binary_path: str, path: str, value: str) -> bool:
    try:
        sub = subprocess.run(
            [binary_path, "config", "set", path, value],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("openclaw config set %s failed: %s", path, exc)
        return False
    if sub.returncode != 0:
        logger.debug("openclaw config set %s: %s", path, sub.stderr.strip())
        return False
    return True


def _configure_engine(binary_path: str, agents: list, engine_id: str) -> None:
    """Empty system override + full tools — Agentira owns persona."""
    idx = next(
        (i for i, a in enumerate(agents)
         if isinstance(a, dict) and a.get("id") == engine_id),
        -1,
    )
    if idx < 0:
        return
    for path, value in [
        (f"agents.list[{idx}].systemPromptOverride", ""),
        (f"agents.list[{idx}].tools", '{"profile":"full"}'),
    ]:
        _config_set(binary_path, path, value)
    # Prefer not seeding SOUL/IDENTITY into Agentira desks when workspace is set.
    _config_set(binary_path, "agents.defaults.skipBootstrap", "true")


def ensure_engine_agent(
    agentira_agent_id: str,
    *,
    workdir: str = "",
    default_model: str = "",
    binary_path: str = "openclaw",
) -> str:
    """Ensure the per-Agentira OpenClaw engine agent exists; bind workspace.

    Returns the OpenClaw engine agent id.
    """
    eng = engine_agent_id(agentira_agent_id)
    agents = _list_agents(binary_path)
    present = any(isinstance(a, dict) and a.get("id") == eng for a in agents)

    if not present:
        model = default_model
        if not model and agents:
            model = next(
                (a.get("model") for a in agents if a.get("isDefault")), ""
            ) or ""
        if not model and agents:
            model = (agents[0].get("model") if isinstance(agents[0], dict) else "") or ""

        # Initial workspace: prefer Agentira desk; else a private empty dir
        # under ~/.agentira so we never share ~/.openclaw/workspace (Bloopy).
        ws = ""
        if workdir and os.path.isdir(workdir):
            ws = os.path.abspath(workdir)
        else:
            ws = str(Path.home() / ".agentira" / "openclaw-engines" / eng)
            os.makedirs(ws, exist_ok=True)

        cmd = [
            binary_path, "agents", "add", eng,
            "--non-interactive", "--json",
            "--workspace", ws,
        ]
        if model:
            cmd += ["--model", model]
        try:
            add = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("openclaw agents add %s failed: %s", eng, exc)
            return eng
        if add.returncode != 0:
            logger.warning(
                "openclaw agents add %s failed: %s", eng, add.stderr.strip(),
            )
            return eng
        logger.info("created OpenClaw engine agent %s workspace=%s", eng, ws)
        _bound_workspace[eng] = ws
        agents = _list_agents(binary_path)
    else:
        _configure_engine(binary_path, agents, eng)

    # Always re-apply contract (idempotent).
    agents = _list_agents(binary_path) or agents
    _configure_engine(binary_path, agents, eng)

    if workdir:
        bind_workspace_if_changed(eng, workdir, binary_path=binary_path, agents=agents)
    return eng


def bind_workspace_if_changed(
    engine_id: str,
    workdir: str,
    *,
    binary_path: str = "openclaw",
    agents: Optional[list] = None,
) -> bool:
    """Point engine agent workspace at Agentira desk. No-op if unchanged.

    Returns True if a config write happened.
    """
    if not workdir or not engine_id:
        return False
    abs_ws = os.path.abspath(workdir)
    if not os.path.isdir(abs_ws):
        logger.warning(
            "openclaw bind workspace skipped (missing dir) eng=%s path=%s",
            engine_id, abs_ws,
        )
        return False

    cached = _bound_workspace.get(engine_id)
    if cached and os.path.abspath(cached) == abs_ws:
        return False

    agents = agents if agents is not None else _list_agents(binary_path)
    current = ""
    idx = -1
    for i, a in enumerate(agents):
        if isinstance(a, dict) and a.get("id") == engine_id:
            current = str(a.get("workspace") or "")
            idx = i
            break
    if idx < 0:
        logger.warning("openclaw bind: engine %s not in agents.list", engine_id)
        return False

    if current and os.path.abspath(os.path.expanduser(current)) == abs_ws:
        _bound_workspace[engine_id] = abs_ws
        return False

    ok = _config_set(
        binary_path,
        f"agents.list[{idx}].workspace",
        abs_ws,
    )
    if ok:
        _bound_workspace[engine_id] = abs_ws
        logger.info(
            "openclaw engine %s workspace -> %s (was %s)",
            engine_id, abs_ws, current or "<unset>",
        )
    return ok


def clear_engine_session(
    session_key: str,
    *,
    binary_path: str = "openclaw",
) -> None:
    """Best-effort OpenClaw-side clear for /clear (ADR 008).

    Prefer ``openclaw sessions`` cleanup; failures are non-fatal — Agentira
    dropping ``runtime_session_id`` is the source of truth for resume.
    """
    key = (session_key or "").strip()
    if not key:
        return
    # OpenClaw CLI has sessions cleanup; reset per-key may be gateway RPC only.
    # Attempt config-less best effort: delete is not exposed cleanly via CLI
    # for arbitrary keys, so we log and rely on backend clearing the handle.
    logger.info("openclaw clear_handle sessionKey=%s (Agentira drops resume id)", key)


def reset_bind_cache() -> None:
    """Test helper."""
    _bound_workspace.clear()
