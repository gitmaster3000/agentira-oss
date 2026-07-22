"""agentira-project MCP server — stdio-based, zero external deps.

Exposes project repo context to agents via MCP tools:
  - read_file(path) — read a file from the project repo
  - list_files(glob, limit) — directory listing
  - read_conventions() — CONVENTIONS.md / AGENTS.md / CLAUDE.md
  - search_repo(query, max_results) — ripgrep or fallback grep

Reads AGENTIRA_REPO_PATH from env. Exits cleanly if unset.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path


REPO_PATH = os.environ.get("AGENTIRA_REPO_PATH", "")

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the project repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path within the repo."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List files in the project repo matching a glob pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "glob": {"type": "string", "description": "Glob pattern (default: **/*)", "default": "**/*"},
                "limit": {"type": "integer", "description": "Max results (default: 200)", "default": 200},
            },
        },
    },
    {
        "name": "read_conventions",
        "description": "Read the project's conventions files (CONVENTIONS.md, AGENTS.md, CLAUDE.md).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_repo",
        "description": "Search the repo for a text pattern (uses ripgrep if available, else grep).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search pattern (literal or regex)."},
                "max_results": {"type": "integer", "description": "Max lines (default: 20)", "default": 20},
            },
            "required": ["query"],
        },
    },
]


def _safe_path(rel: str) -> Path | None:
    """Resolve relative path, rejecting traversals outside the repo."""
    base = Path(REPO_PATH).resolve()
    target = (base / rel).resolve()
    if not str(target).startswith(str(base)):
        return None
    return target


def handle_read_file(args: dict) -> str:
    path = _safe_path(args.get("path", ""))
    if path is None:
        return "Error: path traversal outside repo."
    if not path.exists():
        return f"Error: file not found: {args.get('path')}"
    if not path.is_file():
        return f"Error: not a file: {args.get('path')}"
    try:
        return path.read_text(errors="replace")[:100_000]
    except Exception as e:
        return f"Error reading file: {e}"


def handle_list_files(args: dict) -> str:
    pattern = args.get("glob", "**/*")
    limit = min(args.get("limit", 200), 1000)
    base = Path(REPO_PATH)
    results = []
    for p in base.rglob("*"):
        if p.is_file() and fnmatch.fnmatch(str(p.relative_to(base)), pattern):
            results.append(str(p.relative_to(base)))
            if len(results) >= limit:
                break
    if not results:
        return "No files matched."
    return "\n".join(results)


def handle_read_conventions(args: dict) -> str:
    base = Path(REPO_PATH)
    names = ["CONVENTIONS.md", "AGENTS.md", "CLAUDE.md"]
    parts = []
    for name in names:
        f = base / name
        if f.exists():
            parts.append(f"# {name}\n{f.read_text(errors='replace')[:20_000]}")
    if not parts:
        return "No conventions files found (looked for CONVENTIONS.md, AGENTS.md, CLAUDE.md)."
    return "\n\n---\n\n".join(parts)


def handle_search_repo(args: dict) -> str:
    query = args.get("query", "")
    max_results = min(args.get("max_results", 20), 100)
    if not query:
        return "Error: empty query."

    # Try ripgrep first, fall back to grep.
    for cmd in [
        ["rg", "--no-heading", "-n", "--max-count", str(max_results), query, REPO_PATH],
        ["grep", "-rn", "--include=*", "-m", str(max_results), query, REPO_PATH],
    ]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10, cwd=REPO_PATH,
            )
            if result.returncode <= 1:
                output = result.stdout.strip()
                if output:
                    # Strip the repo path prefix for cleaner output.
                    prefix = REPO_PATH.rstrip("/") + "/"
                    lines = [line.removeprefix(prefix) for line in output.split("\n")]
                    return "\n".join(lines[:max_results])
                return "No matches found."
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return "Error: search timed out."
    return "Error: neither rg nor grep available."


HANDLERS = {
    "read_file": handle_read_file,
    "list_files": handle_list_files,
    "read_conventions": handle_read_conventions,
    "search_repo": handle_search_repo,
}


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentira-project", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if not handler:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True},
            }
        text = handler(tool_args)
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": text}]},
        }

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    if not REPO_PATH:
        sys.stderr.write("AGENTIRA_REPO_PATH not set; exiting.\n")
        sys.exit(1)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
