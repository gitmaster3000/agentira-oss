"""Runtime adapter — pluggable HTTP/RPC client for agent runtimes.

Forge pulls ALL data from runtimes. No filesystem access, no push dependency.
Each runtime type (openclaw, zeroclaw, generic) implements the same interface.

Interface:
  health(url)                    → {online, status, latency_ms}
  chat(url, token, agent, msgs)  → {content, model, input_tokens, output_tokens, cost_usd}
  trigger(url, token, agent, p)  → {success, run_id}
  sessions(url, token, agent)    → [{id, model, tokens, status, ...}]
  activity(url, token, agent)    → [{type, content, tool, tokens, cost, ts}]
  costs(url, token, agent)       → {total_cost, input_tokens, output_tokens, by_model}
"""

from __future__ import annotations
import json
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod


# ── HTTP helper ─────────────────────────────────────────────────────────

def _http(url: str, *, token: str = "", method: str = "GET",
          body: dict | None = None, timeout: int = 10) -> dict:
    """Raw HTTP request → parsed JSON or {_error, _latency_ms}."""
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()

    start = time.monotonic()
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            result["_latency_ms"] = int((time.monotonic() - start) * 1000)
            return result
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:500]
        except Exception:
            pass
        return {"_error": f"HTTP {e.code}: {err_body}",
                "_latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        return {"_error": str(e),
                "_latency_ms": int((time.monotonic() - start) * 1000)}


# ── Adapter interface ──────────────────────────────────────────────────

class RuntimeAdapter(ABC):
    """Base interface for all agent runtimes."""

    @abstractmethod
    def health(self, url: str) -> dict:
        """Is the runtime reachable? → {online, status, latency_ms}"""

    @abstractmethod
    def chat(self, url: str, token: str, agent: str,
             messages: list[dict]) -> dict:
        """Synchronous chat → {content, model, input_tokens, output_tokens, cost_usd, _latency_ms}"""

    @abstractmethod
    def trigger(self, url: str, token: str, agent: str,
                payload: dict) -> dict:
        """Fire-and-forget trigger → {success, run_id, duration_ms}"""

    @abstractmethod
    def sessions(self, url: str, token: str, agent: str) -> list[dict]:
        """Live sessions for this agent → [{id, model, input_tokens, output_tokens, ...}]"""

    @abstractmethod
    def activity(self, url: str, token: str, agent: str,
                 limit: int = 50) -> list[dict]:
        """Recent activity/actions → [{type, role, content, tool_name, tokens, cost, timestamp}]"""

    @abstractmethod
    def costs(self, url: str, token: str, agent: str) -> dict:
        """Usage/cost summary → {total_cost, input_tokens, output_tokens, by_model}"""


# ── OpenClaw adapter ──────────────────────────────────────────────────

def _oc_ws_call(base_url: str, token: str, method: str,
                params: dict | None = None) -> dict | None:
    """Call an OpenClaw gateway WS method using its native protocol.

    Protocol: connect with challenge → handshake → {type:"req"} → {type:"res"}.
    Caches results for 10s to avoid hammering.
    """
    cache_key = f"{base_url}|{method}|{json.dumps(params or {}, sort_keys=True)}"
    now = time.monotonic()
    if cache_key in _oc_ws_cache:
        ts, data = _oc_ws_cache[cache_key]
        if now - ts < 10.0:
            return data

    try:
        import websocket  # type: ignore
    except ImportError:
        return None

    ws_url = base_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/?auth.token={token}"

    try:
        ws = websocket.create_connection(ws_url, timeout=8)
        ws.recv()  # challenge
        # Handshake
        ws.send(json.dumps({
            "type": "req", "id": "c1", "method": "connect",
            "params": {
                "minProtocol": 3, "maxProtocol": 3,
                "client": {"id": "cli", "version": "2026.3.7",
                           "platform": "windows", "mode": "node"},
                "role": "operator",
                "scopes": ["operator.read", "operator.admin"],
                "caps": [], "commands": [], "permissions": {},
                "auth": {"token": token},
                "locale": "en-US", "userAgent": "forge/1.0",
            }
        }))
        hello = json.loads(ws.recv())
        if not hello.get("ok"):
            ws.close()
            return None
        # Send the actual method call
        ws.send(json.dumps({
            "type": "req", "id": "m1",
            "method": method, "params": params or {},
        }))
        # Read frames until we get our response (skip events)
        for _ in range(20):
            frame = json.loads(ws.recv())
            if frame.get("type") == "res" and frame.get("id") == "m1":
                ws.close()
                if frame.get("ok"):
                    result = frame.get("payload", {})
                    _oc_ws_cache[cache_key] = (now, result)
                    return result
                return None
        ws.close()
        return None
    except Exception:
        return None


_oc_ws_cache: dict[str, tuple[float, dict]] = {}


class OpenClawAdapter(RuntimeAdapter):
    """OpenClaw runtime — HTTP gateway + hooks.

    Available endpoints:
      GET  /health
      POST /v1/chat/completions  (needs gateway.http.endpoints.chatCompletions.enabled)
      POST /hooks/agent          (needs hooks.enabled + token)
    """

    def health(self, url: str) -> dict:
        result = _http(url.rstrip("/") + "/health")
        if "_error" in result:
            return {"online": False, "error": result["_error"],
                    "latency_ms": result.get("_latency_ms")}
        return {
            "online": result.get("ok", False),
            "status": result.get("status", "unknown"),
            "latency_ms": result.get("_latency_ms"),
        }

    def chat(self, url: str, token: str, agent: str,
             messages: list[dict]) -> dict:
        endpoint = url.rstrip("/") + "/v1/chat/completions"
        # Route through the generic `agentira-runner` agent regardless of
        # which Agentira agent is asking. Agentira owns the persona; OpenClaw
        # contributes only its tools/workspace via this runner. The `agent`
        # parameter is unused for routing — kept for signature compatibility
        # with the legacy /hooks/agent path. See AP-70 + the runtime
        # architecture plan.
        body = {
            "model": "openclaw:agentira-runner",
            "messages": messages,
            "stream": False,
        }
        result = _http(endpoint, token=token, method="POST",
                       body=body, timeout=120)
        if "_error" in result:
            return result

        # Parse OpenAI-compatible response
        content = ""
        model = result.get("model", "")
        choices = result.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")

        usage = result.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # If runtime reports zero tokens, estimate from content (~4 chars/token)
        if not input_tokens:
            input_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        if not output_tokens:
            output_tokens = len(content) // 4

        # Cost from response extensions, or zero (caller estimates from pricing table)
        cost_usd = 0.0
        if "cost" in result:
            cost_usd = result["cost"]
        elif "x_openclaw" in result:
            cost_usd = result["x_openclaw"].get("cost_usd", 0.0)
        elif "cost" in usage:
            cost_usd = usage["cost"].get("total", 0.0) if isinstance(usage["cost"], dict) else usage["cost"]

        return {
            "content": content,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
            "_latency_ms": result.get("_latency_ms", 0),
        }

    def trigger(self, url: str, token: str, agent: str,
                payload: dict) -> dict:
        endpoint = url.rstrip("/") + "/hooks/agent"
        body = {"agentId": agent, **payload}
        result = _http(endpoint, token=token, method="POST",
                       body=body, timeout=30)
        if "_error" in result:
            return {"success": False, "error": result["_error"],
                    "duration_ms": result.get("_latency_ms")}
        return {
            "success": result.get("ok", True),
            "run_id": result.get("runId"),
            "duration_ms": result.get("_latency_ms"),
        }

    def sessions(self, url: str, token: str, agent: str) -> list[dict]:
        data = _oc_ws_call(url, token, "status")
        if not data:
            return []
        all_sessions = data.get("sessions", {}).get("recent", [])
        return [s for s in all_sessions if s.get("agentId") == agent]

    def activity(self, url: str, token: str, agent: str,
                 limit: int = 50) -> list[dict]:
        # Activity details not yet exposed via WS protocol
        return []

    def costs(self, url: str, token: str, agent: str) -> dict:
        """Aggregate cost from all sessions for this agent."""
        data = _oc_ws_call(url, token, "status")
        if not data:
            return {}
        all_sessions = data.get("sessions", {}).get("recent", [])
        agent_sessions = [s for s in all_sessions if s.get("agentId") == agent]
        total_input = sum(s.get("inputTokens", 0) for s in agent_sessions)
        total_output = sum(s.get("outputTokens", 0) for s in agent_sessions)
        total_cache_read = sum(s.get("cacheRead", 0) for s in agent_sessions)
        model = agent_sessions[0].get("model", "") if agent_sessions else ""
        # Estimate cost from tokens
        from backend.forge.services import estimate_cost
        est = estimate_cost(model, total_input, total_output)
        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cache_read": total_cache_read,
            "total_tokens": total_input + total_output,
            "session_count": len(agent_sessions),
            "model": model,
            "estimated_cost_usd": est.get("total_cost", 0.0),
            "pricing_found": est.get("pricing_found", False),
        }


# ── Generic OpenAI-compatible adapter ──────────────────────────────────

class GenericAdapter(RuntimeAdapter):
    """Any OpenAI-compatible runtime (local LLMs, other gateways)."""

    def health(self, url: str) -> dict:
        # Try /health, fall back to /v1/models
        result = _http(url.rstrip("/") + "/health")
        if "_error" not in result:
            return {"online": True, "status": "live",
                    "latency_ms": result.get("_latency_ms")}
        result = _http(url.rstrip("/") + "/v1/models")
        if "_error" not in result:
            return {"online": True, "status": "live",
                    "latency_ms": result.get("_latency_ms")}
        return {"online": False, "error": result["_error"],
                "latency_ms": result.get("_latency_ms")}

    def chat(self, url: str, token: str, agent: str,
             messages: list[dict]) -> dict:
        endpoint = url.rstrip("/") + "/v1/chat/completions"
        body = {"model": agent, "messages": messages, "stream": False}
        result = _http(endpoint, token=token, method="POST",
                       body=body, timeout=120)
        if "_error" in result:
            return result
        content = ""
        model = result.get("model", "")
        choices = result.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
        usage = result.get("usage", {})
        return {
            "content": content,
            "model": model,
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "cost_usd": 0.0,
            "_latency_ms": result.get("_latency_ms", 0),
        }

    def trigger(self, url: str, token: str, agent: str,
                payload: dict) -> dict:
        return {"success": False, "error": "Generic runtime has no trigger endpoint"}

    def sessions(self, url: str, token: str, agent: str) -> list[dict]:
        return []

    def activity(self, url: str, token: str, agent: str,
                 limit: int = 50) -> list[dict]:
        return []

    def costs(self, url: str, token: str, agent: str) -> dict:
        return {}


# ── Ollama adapter ─────────────────────────────────────────────────────

class OllamaAdapter(GenericAdapter):
    """Ollama runtime — bare LLM gateway via OpenAI-compatible endpoint.

    Per the runtime architecture: Agentira owns persona/MCP/workspace; Ollama
    just generates tokens. The only thing this adapter does on top of
    GenericAdapter is strip the `ollama/` prefix from model strings before
    sending — Agentira surfaces models as `ollama/qwen3.6:latest` for
    unambiguous routing, but Ollama's own API expects just `qwen3.6:latest`.
    """

    def chat(self, url: str, token: str, agent: str,
             messages: list[dict]) -> dict:
        # `agent` here is the model id (the chat path passes a.model down).
        if agent.startswith("ollama/"):
            agent = agent[len("ollama/"):]
        return super().chat(url, token, agent, messages)


# ── Adapter registry ──────────────────────────────────────────────────

_ADAPTERS: dict[str, RuntimeAdapter] = {
    "openclaw": OpenClawAdapter(),
    "zeroclaw": OpenClawAdapter(),   # same protocol for now
    "ollama":   OllamaAdapter(),
    "openai":   GenericAdapter(),
    "grok":     GenericAdapter(),    # xAI Grok API (OpenAI-compatible)
    "generic":  GenericAdapter(),
}


def get_adapter(runtime_type: str) -> RuntimeAdapter:
    """Get the adapter for a runtime type."""
    return _ADAPTERS.get(runtime_type, _ADAPTERS["openclaw"])


# ── Convenience functions (backward compat for services.py) ────────────

def check_health(url: str, runtime_type: str = "openclaw") -> dict:
    return get_adapter(runtime_type).health(url)


def send_chat(url: str, token: str, agent: str, messages: list[dict],
              runtime_type: str = "openclaw") -> dict:
    return get_adapter(runtime_type).chat(url, token, agent, messages)


def trigger_hook(url: str, token: str, agent: str, payload: dict,
                 runtime_type: str = "openclaw") -> dict:
    return get_adapter(runtime_type).trigger(url, token, agent, payload)


def get_sessions(url: str, token: str, agent: str,
                 runtime_type: str = "openclaw") -> list[dict]:
    return get_adapter(runtime_type).sessions(url, token, agent)


def get_activity(url: str, token: str, agent: str, limit: int = 50,
                 runtime_type: str = "openclaw") -> list[dict]:
    return get_adapter(runtime_type).activity(url, token, agent, limit)


def get_costs(url: str, token: str, agent: str,
              runtime_type: str = "openclaw") -> dict:
    return get_adapter(runtime_type).costs(url, token, agent)
