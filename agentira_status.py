#!/usr/bin/env python3
"""
Agentira system status CLI.
Reads component definitions from agentira_components.json.

Usage:
  python agentira_status.py            # one-shot table
  python agentira_status.py --watch    # refresh every 5s
  python agentira_status.py -i 10      # watch with 10s interval
  python agentira_status.py --json     # machine-readable output
"""
import argparse
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# Force UTF-8 output on Windows
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

CONFIG_FILE = Path(__file__).parent / "agentira_components.json"

# ── Colours ───────────────────────────────────────────────────────────────────

USE_COLOR = sys.stdout.isatty()

def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

GREEN  = lambda t: _c("32", t)
RED    = lambda t: _c("31", t)
YELLOW = lambda t: _c("33", t)
CYAN   = lambda t: _c("36", t)
BOLD   = lambda t: _c("1",  t)
DIM    = lambda t: _c("2",  t)

# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class Component:
    label: str
    port: int
    kind: str
    health_url: str | None = None
    dashboard_via: int | None = None   # proxy port for this agent
    # filled at runtime
    listening: bool = False
    healthy: bool | None = None        # None = not checked
    pid: str = "-"
    cmd: str = ""


def load_config(path: Path = CONFIG_FILE) -> list[Component]:
    if not path.exists():
        print(f"Config not found: {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(path.read_text())
    return [Component(**c) for c in data["components"]]


# ── Checks ────────────────────────────────────────────────────────────────────

def port_listening(port: int) -> bool:
    for family, addr in [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((addr, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status < 500
    except Exception:
        return False


def pid_for_port(port: int) -> str:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if f":{port} " in line and "LISTEN" in line:
                return line.split()[-1]
    except Exception:
        pass
    return "-"


def cmdline_for_pid(pid: str) -> str:
    if pid == "-":
        return ""
    try:
        out = subprocess.check_output(
            ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
            text=True, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
        )
        lines = [l.strip() for l in out.splitlines() if l.strip() and "CommandLine" not in l]
        if lines:
            cmd = lines[0]
            # shorten noisy Windows paths
            cmd = cmd.replace(
                "C:\\Users\\ali_f\\AppData\\Local\\Programs\\Python\\Python313\\python.exe", "python"
            )
            cmd = cmd.replace("C:\\Users\\ali_f\\.cargo\\bin\\zeroclaw.exe", "zeroclaw")
            return cmd[:60]
    except Exception:
        pass
    return ""


def gather(components: list[Component]) -> None:
    for c in components:
        c.listening = port_listening(c.port)
        if c.listening:
            c.pid = pid_for_port(c.port)
            c.cmd = cmdline_for_pid(c.pid)
            if c.health_url:
                c.healthy = http_ok(c.health_url)
        else:
            c.pid = "-"
            c.cmd = ""
            c.healthy = None


# ── Display ───────────────────────────────────────────────────────────────────

KIND_ICON = {"agentira": "🟦", "zeroclaw": "🟩", "proxy": "🔀"}


def status_cell(c: Component) -> str:
    if not c.listening:
        return RED("DOWN   ")
    if c.healthy is False:
        return YELLOW("WARN   ")
    return GREEN("UP     ")


def print_table(components: list[Component]) -> None:
    print()
    print(BOLD("  Agentira System Status"))
    print(DIM("  " + "─" * 70))
    print(f"  {'Component':<22} {'Port':>5}  {'Status'}   {'PID':>7}  {'Process'}")
    print(DIM("  " + "─" * 70))

    last_kind = None
    for c in components:
        if c.kind != last_kind:
            print()
            last_kind = c.kind
        icon = KIND_ICON.get(c.kind, "  ")
        pid_str = DIM(c.pid)
        cmd_str = DIM(c.cmd) if c.cmd else ""
        print(f"  {icon} {c.label:<20} {c.port:>5}  {status_cell(c)}  {pid_str:>7}  {cmd_str}")

    print(DIM("  " + "─" * 70))

    # Dashboard links for agents that have a proxy
    agents_with_proxy = [c for c in components if c.kind == "zeroclaw" and c.dashboard_via]
    if agents_with_proxy:
        print()
        print(BOLD("  Agent Dashboards (via proxy)"))
        for c in agents_with_proxy:
            state = GREEN("up") if c.listening else RED("down")
            print(f"    {CYAN(c.label):<28}  http://localhost:{c.dashboard_via}  [{state}]")

    # Summary line
    up   = sum(1 for c in components if c.listening)
    down = len(components) - up
    print()
    if down == 0:
        print(f"  {GREEN('All ' + str(up) + ' components running.')}")
    else:
        print(f"  {GREEN(str(up) + ' up')}  {RED(str(down) + ' down')}")
    print()


def print_json_out(components: list[Component]) -> None:
    out = [
        {
            "label": c.label, "port": c.port, "kind": c.kind,
            "listening": c.listening, "healthy": c.healthy, "pid": c.pid,
        }
        for c in components
    ]
    print(json.dumps(out, indent=2))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Agentira system status")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Refresh every N seconds (Ctrl+C to quit)")
    parser.add_argument("--interval", "-i", type=int, default=5,
                        help="Watch interval in seconds (default: 5)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON and exit")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE,
                        help=f"Component config file (default: {CONFIG_FILE})")
    args = parser.parse_args()

    config_path = args.config

    if args.json:
        components = load_config(config_path)
        gather(components)
        print_json_out(components)
        return

    if args.watch:
        try:
            while True:
                print("\033[2J\033[H" if USE_COLOR else "", end="")
                components = load_config(config_path)
                gather(components)
                print_table(components)
                print(DIM(f"  Refreshing every {args.interval}s — Ctrl+C to quit"))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        components = load_config(config_path)
        gather(components)
        print_table(components)


if __name__ == "__main__":
    main()
