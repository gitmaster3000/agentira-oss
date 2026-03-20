#!/usr/bin/env python3
"""
Agentira system status CLI.
Reads component definitions from agentira_components.json.

Usage:
  python agentira_status.py            # one-shot table
  python agentira_status.py kill <label>
  python agentira_status.py start <label>
  python agentira_status.py reload <label>
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
    command: str | None = None
    health_url: str | None = None
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
        if os.name == "nt":
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
            )
            for line in out.splitlines():
                if f":{port} " in line and "LISTEN" in line:
                    return line.split()[-1]
        else:
            # lsof -t -i :PORT
            out = subprocess.check_output(
                ["lsof", "-t", f"-i:{port}"], text=True, stderr=subprocess.DEVNULL
            )
            return out.strip().split('\n')[0]
    except Exception:
        pass
    return "-"


def cmdline_for_pid(pid: str) -> str:
    if pid == "-":
        return ""
    try:
        if os.name == "nt":
            out = subprocess.check_output(
                ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
                text=True, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace",
            )
            lines = [l.strip() for l in out.splitlines() if l.strip() and "CommandLine" not in l]
            if lines:
                return lines[0][:60]
        else:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().replace(b"\0", b" ").decode(errors="replace")
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


# ── Actions ───────────────────────────────────────────────────────────────────

def kill_component(c: Component) -> bool:
    if not c.listening or c.pid == "-":
        print(f"  {YELLOW(c.label)} is not running.")
        return False
    print(f"  Killing {BOLD(c.label)} (PID {c.pid})...")
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", c.pid], check=True, capture_output=True)
        else:
            import signal
            os.killpg(os.getpgid(int(c.pid)), signal.SIGTERM)
        print(f"  {GREEN('Killed.')}")
        return True
    except Exception as e:
        print(f"  {RED('Failed to kill:')} {e}")
        return False


def start_component(c: Component) -> bool:
    if c.listening:
        print(f"  {YELLOW(c.label)} is already running (PID {c.pid}).")
        return False
    if not c.command:
        print(f"  {RED('No start command defined')} for {c.label}")
        return False

    print(f"  Starting {BOLD(c.label)}: {DIM(c.command)}...")
    try:
        if os.name == "nt":
            subprocess.Popen(c.command, shell=True, start_new_session=True, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            subprocess.Popen(c.command, shell=True, preexec_fn=os.setsid)
        print(f"  {GREEN('Started.')}")
        return True
    except Exception as e:
        print(f"  {RED('Failed to start:')} {e}")
        return False


# ── Display ───────────────────────────────────────────────────────────────────

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
    print(f"  {'Component':<30} {'Port':>5}  {'Status'}   {'PID':>7}  {'Process'}")
    print(DIM("  " + "─" * 70))

    for c in components:
        pid_str = DIM(c.pid)
        cmd_str = DIM(c.cmd) if c.cmd else ""
        print(f"   {c.label:<30} {c.port:>5}  {status_cell(c)}  {pid_str:>7}  {cmd_str}")

    print(DIM("  " + "─" * 70))

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
    parser.add_argument("--config", type=Path, default=CONFIG_FILE, help=f"Config file")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    
    subparsers = parser.add_subparsers(dest="action")
    status_p = subparsers.add_parser("status")
    
    kill_p = subparsers.add_parser("kill")
    kill_p.add_argument("label")
    
    start_p = subparsers.add_parser("start")
    start_p.add_argument("label")
    
    reload_p = subparsers.add_parser("reload")
    reload_p.add_argument("label")

    args, unknown = parser.parse_known_args()

    components = load_config(args.config)
    gather(components)

    if args.action in ["kill", "start", "reload"]:
        target = next((c for c in components if args.label.lower() in c.label.lower()), None)
        if not target:
            print(f"  {RED('Component not found:')} {args.label}")
            sys.exit(1)

        if args.action == "kill":
            kill_component(target)
        elif args.action == "start":
            start_component(target)
        elif args.action == "reload":
            kill_component(target)
            time.sleep(1)
            target.listening = False
            start_component(target)
        return

    if args.json:
        print_json_out(components)
    else:
        print_table(components)


if __name__ == "__main__":
    main()
