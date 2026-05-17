#!/usr/bin/env python3
"""Bootstrap an 8-agent fleet on an Agentira project.

Creates the agent fleet described in the Leadcore handover plan:
  - 4 agents on the Claude runtime  (full MCP + native resume)
  - 2 agents on OpenClaw / Qwen     (MCP via AP-103 per-dispatch register)
  - 2 agents on OpenClaw / Kimi 2.6 (same)

Each agent gets a role-specific system prompt, is bound to the target
project, added as a project member, and (optionally) has the Conductor
enabled so it auto-picks todo tasks.

This is a setup helper, not production code. It's idempotent on agent
name — re-running updates existing agents instead of duplicating.

Usage:
    python scripts/bootstrap_agents.py \
        --api-url http://localhost:8111 \
        --api-key <ADMIN_API_KEY> \
        --project-id 891ab97ee6ca \
        --enable-conductor

Runtimes must already be registered — start the daemon first
(`agentira daemon start`) so Claude + OpenClaw runtimes appear in
GET /api/forge/runtimes.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


# ── Agent fleet definition ───────────────────────────────────────────────
# runtime: "claude" | "openclaw". model: passed through to the runtime.
# conductor: whether this agent auto-picks todo tasks.
FLEET = [
    {
        "name": "planner",
        "runtime": "claude",
        "model": "claude-sonnet-4-5",
        "conductor": False,
        "system_prompt": (
            "You are the Planner for the Agentira project. You read incoming "
            "goals, break them into well-scoped tasks with clear acceptance "
            "criteria, and create them on the board via the agentira MCP "
            "tools. You do NOT write code. Keep tasks small enough for one "
            "agent to finish in a single run."
        ),
    },
    {
        "name": "reviewer",
        "runtime": "claude",
        "model": "claude-sonnet-4-5",
        "conductor": False,
        "system_prompt": (
            "You are the Reviewer for the Agentira project. You review work "
            "produced by other agents: read their diffs, verify tests exist "
            "and pass, check the change matches the task's acceptance "
            "criteria. Move tasks review->done only with evidence. Comment "
            "concrete fixes when rejecting. You must NOT review your own work."
        ),
    },
    {
        "name": "implementer-1",
        "runtime": "claude",
        "model": "claude-sonnet-4-5",
        "conductor": True,
        "system_prompt": (
            "You are Implementer-1 for the Agentira project. You pick up a "
            "todo task, implement it with minimal surgical changes, write or "
            "update tests, verify them, and finish the run with a clear "
            "summary. Follow the conventions in CLAUDE.md. Call finish_run "
            "with an honest outcome."
        ),
    },
    {
        "name": "implementer-2",
        "runtime": "claude",
        "model": "claude-sonnet-4-5",
        "conductor": True,
        "system_prompt": (
            "You are Implementer-2 for the Agentira project. Same role as "
            "Implementer-1: pick up a todo task, implement minimally, test, "
            "finish with an honest outcome. Follow CLAUDE.md conventions."
        ),
    },
    {
        "name": "implementer-qwen-1",
        "runtime": "openclaw",
        "model": "ollama/qwen3.6",
        "conductor": True,
        "system_prompt": (
            "You are Implementer-Qwen-1 for the Agentira project. Pick up a "
            "todo task and implement it. Prefer small, well-tested changes. "
            "Use the agentira MCP tools to read tasks and report progress. "
            "If a task is ambiguous, finish with outcome=blocked and a clear "
            "reason rather than guessing."
        ),
    },
    {
        "name": "implementer-qwen-2",
        "runtime": "openclaw",
        "model": "ollama/qwen3.6",
        "conductor": True,
        "system_prompt": (
            "You are Implementer-Qwen-2 for the Agentira project. Same role "
            "as Implementer-Qwen-1. Small tested changes; block honestly on "
            "ambiguity."
        ),
    },
    {
        "name": "implementer-kimi-1",
        "runtime": "openclaw",
        "model": "kimi/kimi-2.6",
        "conductor": True,
        "system_prompt": (
            "You are Implementer-Kimi-1 for the Agentira project. Pick up a "
            "todo task and implement it with minimal, well-tested changes. "
            "Use the agentira MCP tools. Block honestly on ambiguity."
        ),
    },
    {
        "name": "test-writer-kimi",
        "runtime": "openclaw",
        "model": "kimi/kimi-2.6",
        "conductor": True,
        "system_prompt": (
            "You are the Test-Writer for the Agentira project. You pick up "
            "tasks tagged with test work, or add missing coverage for "
            "recently-merged changes. Write focused unit tests, run them, "
            "and finish with an honest outcome."
        ),
    },
]


# ── HTTP helpers ─────────────────────────────────────────────────────────

def _req(method: str, url: str, api_key: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        raise SystemExit(f"HTTP {e.code} on {method} {url}: {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach {url}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Bootstrap the 8-agent fleet.")
    ap.add_argument("--api-url", default="http://localhost:8111")
    ap.add_argument("--api-key", required=True, help="Admin API key")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--enable-conductor", action="store_true",
                    help="Turn on conductor_enabled for implementer agents")
    args = ap.parse_args()

    base = args.api_url.rstrip("/")
    key = args.api_key

    # 1. Resolve runtimes — need one claude + one openclaw.
    runtimes = _req("GET", f"{base}/api/forge/runtimes", key)
    rt_by_provider: dict[str, str] = {}
    for rt in runtimes if isinstance(runtimes, list) else []:
        prov = rt.get("provider")
        if prov and prov not in rt_by_provider:
            rt_by_provider[prov] = rt.get("id")
    print(f"Runtimes online: {', '.join(rt_by_provider) or '(none)'}")

    missing = {a["runtime"] for a in FLEET} - set(rt_by_provider)
    if missing:
        raise SystemExit(
            f"Required runtime(s) not registered: {', '.join(sorted(missing))}. "
            "Start the daemon (`agentira daemon start`) and retry."
        )

    # 2. Existing agents — for idempotent re-runs.
    existing = _req("GET", f"{base}/api/forge/agents", key)
    by_name = {a["name"]: a for a in (existing if isinstance(existing, list) else [])}

    created, updated = [], []
    for spec in FLEET:
        runtime_id = rt_by_provider[spec["runtime"]]
        conductor_on = args.enable_conductor and spec["conductor"]

        if spec["name"] in by_name:
            agent_id = by_name[spec["name"]]["id"]
            updated.append(spec["name"])
        else:
            agent = _req("POST", f"{base}/api/forge/agents", key, {
                "name": spec["name"],
                "runtime_id": runtime_id,
                "model": spec["model"],
            })
            agent_id = agent["id"]
            created.append(spec["name"])

        # Configure: prompt, project binding, model, conductor.
        _req("PATCH", f"{base}/api/forge/agents/{agent_id}", key, {
            "runtime_id": runtime_id,
            "model": spec["model"],
            "system_prompt": spec["system_prompt"],
            "default_project_id": args.project_id,
            "conductor_enabled": conductor_on,
            "max_concurrent_runs": 1,
        })

        # Add as a project member (idempotent — ignore "already a member").
        try:
            _req("POST", f"{base}/api/projects/{args.project_id}/members", key,
                 {"profile_name": spec["name"]})
        except SystemExit as e:
            if "already" not in str(e).lower():
                raise

        flags = f"runtime={spec['runtime']} model={spec['model']}"
        if conductor_on:
            flags += " conductor=ON"
        print(f"  ✓ {spec['name']:22s} {flags}")

    print(f"\nDone. Created {len(created)}, updated {len(updated)}.")
    if args.enable_conductor:
        print("Conductor is ON for implementer agents — they will auto-pick "
              "todo tasks within ~60s.")
    else:
        print("Conductor left OFF. Re-run with --enable-conductor to enable "
              "autonomous pickup, or toggle per-agent in the UI.")


if __name__ == "__main__":
    main()
