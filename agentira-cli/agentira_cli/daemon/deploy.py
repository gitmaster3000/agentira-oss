"""Local Docker deploys — run a project's branch on this machine.

The backend can't reach the host's Docker, so it sends a `deploy` frame and
this module does the work, reporting back through `report(**fields)` (the
daemon POSTs each call to /api/forge/daemon/deploy-result). Actions:

  deploy    clone the repo at `ref` into DEPLOYS_DIR/<project>/<branch>/src
            (daemon-owned, never an agent worktree), then
            `docker compose up -d --build` when the repo has a compose file,
            else `docker build` + `docker run`; health-probe the public port.
  status    live / crashed / stopped from the labelled containers.
  logs      recent output of every labelled container.
  teardown  remove containers, networks, volumes, images and the checkout.

Naming: the backend's handle is `<runtime_id>:<key>`; `key` is the compose
project / container / image name and the value of the `agentira.deploy`
label on everything we start. The public port is derived from the key and
bound to 127.0.0.1 only; compose ports are remapped through an override file
so two branches of the same app never collide.

Every value that reaches git/docker is validated first and passed as an argv
element — never through a shell.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

logger = logging.getLogger("agentira.daemon.deploy")

DEPLOYS_DIR = Path.home() / ".agentira" / "deploys"
PORT_RANGE = (20000, 30000)
LABEL_DEPLOY = "agentira.deploy"
LABEL_PROJECT = "agentira.project"
LABEL_BRANCH = "agentira.branch"
COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
BUILD_TIMEOUT_S = 1200
HEALTH_TIMEOUT_S = 180
LOG_TAIL = 200

_KEY_PREFIX = "agentira-"
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_KEY_RE = re.compile(r"^agentira-[a-z0-9][a-z0-9-]{0,62}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SERVICE_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
_PATH_RE = re.compile(r"^/[A-Za-z0-9._~/?&=%-]{0,199}$")
_URL_RE = re.compile(r"^(https?://|ssh://|file:///|git@)[A-Za-z0-9@:/._~%+-]+$")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()

Report = Callable[..., None]


class DeployError(Exception):
    """A deploy step failed; the message is shown to the user as-is."""


# ── validation / naming ───────────────────────────────────────────────────

def validate_ref(ref: str) -> str:
    ref = (ref or "").strip()
    if not _REF_RE.match(ref) or ".." in ref or ref.endswith((".lock", "/", ".")):
        raise ValueError(f"{ref!r} is not a branch name we can deploy")
    return ref


def validate_source_url(url: str) -> str:
    url = (url or "").strip()
    if not _URL_RE.match(url) or ".." in url:
        raise ValueError("the project's repository address isn't one we can clone")
    return url


def _validate(pattern: re.Pattern, value, what: str) -> str:
    value = str(value or "")
    if not pattern.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def preferred_port(key: str) -> int:
    lo, hi = PORT_RANGE
    return lo + int(hashlib.sha256(key.encode()).hexdigest(), 16) % (hi - lo)


def workdir(project_id: str, key: str) -> Path:
    return DEPLOYS_DIR / project_id / key[len(_KEY_PREFIX):]


def _find_workdir(key: str) -> Path | None:
    if not DEPLOYS_DIR.is_dir():
        return None
    return next((p for p in DEPLOYS_DIR.glob(f"*/{key[len(_KEY_PREFIX):]}") if p.is_dir()), None)


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pick_port(key: str, previous: int | None) -> int:
    # A redeploy keeps its URL: our own containers hold the port and are
    # replaced in place.
    if previous and (_port_free(previous) or _container_ids(key)):
        return previous
    lo, hi = PORT_RANGE
    start = preferred_port(key)
    for i in range(200):
        port = lo + (start - lo + i) % (hi - lo)
        if _port_free(port):
            return port
    raise DeployError("No free port was found on this computer for the preview.")


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# ── process helpers ───────────────────────────────────────────────────────

def _env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.update(extra or {})
    return env


def _run(args: list[str], *, cwd: Path | None = None, timeout: float = 120,
         env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env or _env())


class _Log:
    """Collects output lines and streams them to the backend at most every
    few seconds while a deploy is building."""

    def __init__(self, report: Report, every_s: float = 3.0):
        self.lines: list[str] = []
        self._report = report
        self._every = every_s
        self._last = 0.0

    def add(self, *lines: str, flush: bool = False) -> None:
        self.lines.extend(line.rstrip() for line in lines if line.strip())
        self.lines = self.lines[-2000:]
        if flush or time.monotonic() - self._last >= self._every:
            self._last = time.monotonic()
            self._report(status="building", logs=self.tail())

    def tail(self, n: int = 500) -> list[str]:
        return self.lines[-n:]


def _step(log: _Log, args: list[str], *, failure: str, cwd: Path | None = None,
          timeout: float = 120, env: dict | None = None) -> str:
    """Run one command, streaming its output into `log`. Raises DeployError
    with the plain-language `failure` if it exits non-zero."""
    try:
        proc = subprocess.Popen(args, cwd=cwd, env=env or _env(), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        raise DeployError(f"{failure} ({exc})") from exc
    deadline = time.monotonic() + timeout
    out: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        out.append(line)
        log.add(line)
        if time.monotonic() > deadline:
            proc.kill()
            raise DeployError(f"{failure} (took longer than {int(timeout)}s)")
    if proc.wait() != 0:
        raise DeployError(failure)
    return "".join(out)


# ── actions ───────────────────────────────────────────────────────────────

def handle(frame: dict, report: Report) -> None:
    """Run one `deploy` frame and report the outcome. Never raises."""
    action = frame.get("action") or "deploy"
    handle_id = frame.get("deployment_id") or ""
    key = handle_id.partition(":")[2]
    try:
        _validate(_KEY_RE, key, "deployment name")
        with _lock(key):
            if action == "deploy":
                _deploy(frame, key, report)
            elif action == "teardown":
                _teardown(key)
                report(status="stopped", logs=None)
            elif action == "status":
                report(**_status(key))
            elif action == "logs":
                report(logs=_logs(key))
            else:
                raise ValueError(f"unknown deploy action {action!r}")
    except (DeployError, ValueError) as exc:
        report(status="failed", detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — report, never kill the daemon
        logger.exception("deploy %s %s crashed", action, key)
        report(status="failed", detail=f"Deploy stopped unexpectedly: {exc}")


def _deploy(frame: dict, key: str, report: Report) -> None:
    project_id = _validate(_ID_RE, frame.get("project_id"), "project id")
    branch = validate_ref(frame.get("branch") or "")
    ref = validate_ref(frame.get("ref") or branch)
    source_url = validate_source_url(frame.get("source_url") or "")
    config = frame.get("config") or {}
    health_path = _validate(_PATH_RE, config.get("health_path") or "/", "health check path")
    service = config.get("service")
    if service:
        _validate(_SERVICE_RE, service, "service name")
    container_port = config.get("container_port")
    if container_port is not None:
        container_port = int(container_port)
        if not 0 < container_port < 65536:
            raise ValueError(f"invalid container port: {container_port}")

    wd = workdir(project_id, key)
    src = wd / "src"
    state_file = wd / "deploy.json"
    state = json.loads(state_file.read_text()) if state_file.is_file() else {}
    log = _Log(report)
    log.add(f"Getting the code for {branch}…", flush=True)

    src.mkdir(parents=True, exist_ok=True)
    if not (src / ".git").is_dir():
        _step(log, ["git", "init", "-q", str(src)], failure="Couldn't prepare a folder for the code.")
    _run(["git", "-C", str(src), "remote", "remove", "origin"])
    _step(log, ["git", "-C", str(src), "remote", "add", "origin", source_url],
          failure="Couldn't set the repository address.")
    _step(log, ["git", "-C", str(src), "fetch", "-q", "--depth", "1", "origin", ref],
          failure=f"Couldn't download {ref} from the repository.", timeout=600)
    _step(log, ["git", "-C", str(src), "checkout", "-q", "--force", "--detach", "FETCH_HEAD"],
          failure=f"Couldn't check out {ref}.")
    _step(log, ["git", "-C", str(src), "clean", "-q", "-fdx"], failure="Couldn't clean the code folder.")

    port = _pick_port(key, state.get("port"))
    labels = {LABEL_DEPLOY: key, LABEL_PROJECT: project_id, LABEL_BRANCH: branch}
    compose_file = next((src / f for f in COMPOSE_FILES if (src / f).is_file()), None)
    if compose_file is not None:
        mode = "compose"
        _compose_up(log, key, src, wd, compose_file, port, labels, service, container_port)
    else:
        mode = "dockerfile"
        _container_up(log, key, src, port, labels, container_port)
    wd.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"key": key, "port": port, "mode": mode,
                                      "branch": branch, "ref": ref}))

    url = f"http://127.0.0.1:{port}"
    log.add(f"Waiting for the app to answer on {health_path}…", flush=True)
    if not _healthy(url + health_path):
        log.add(*_logs(key))
        report(status="failed", url=url, logs=log.tail(),
               detail=f"The app started but never answered on {health_path} — "
                      "open the logs to see why.")
        return
    log.add(f"Live at {url}")
    report(status="live", url=url, logs=log.tail())


def _compose_up(log: _Log, key: str, src: Path, wd: Path, compose_file: Path,
                port: int, labels: dict, service: str | None,
                container_port: int | None) -> None:
    base = ["docker", "compose", "-p", key, "-f", str(compose_file)]
    raw = _step(log, [*base, "config", "--format", "json"], cwd=src,
                failure="The docker compose file has an error.")
    services = json.loads(raw[raw.index("{"):]).get("services") or {}
    if not services:
        raise DeployError("The docker compose file defines no services.")
    public = service or next((n for n, s in services.items() if s.get("ports")), None)
    if public not in services:
        raise DeployError("None of the compose services publishes a port — "
                          "set which service is the public one.")
    if container_port is None:
        ports = services[public].get("ports") or []
        container_port = int(ports[0]["target"]) if ports else 80

    lines = ["services:"]
    for name, spec in services.items():
        _validate(_SERVICE_RE, name, "service name")
        lines.append(f"  {json.dumps(name)}:")
        if name == public:
            lines += ["    ports: !override",
                      f"      - {json.dumps(f'127.0.0.1:{port}:{container_port}')}"]
        elif spec.get("ports"):
            lines.append("    ports: !reset []")
        lines.append("    labels:")
        lines += [f"      {json.dumps(k)}: {json.dumps(v)}" for k, v in labels.items()]
    override = wd / "agentira.override.yaml"
    override.write_text("\n".join(lines) + "\n")

    log.add("Building and starting the app with docker compose…", flush=True)
    _step(log, [*base, "-f", str(override), "up", "-d", "--build", "--remove-orphans"],
          cwd=src, timeout=BUILD_TIMEOUT_S, env=_env({"AGENTIRA_PORT": str(port)}),
          failure="docker compose couldn't build or start the app.")


def _container_up(log: _Log, key: str, src: Path, port: int, labels: dict,
                  container_port: int | None) -> None:
    if not (src / "Dockerfile").is_file():
        raise DeployError("This repository has neither a docker compose file "
                          "nor a Dockerfile, so there's nothing to run.")
    image = f"{key}:latest"
    label_args = [a for k, v in labels.items() for a in ("--label", f"{k}={v}")]
    log.add("Building the app image…", flush=True)
    _step(log, ["docker", "build", "-t", image, *label_args, str(src)],
          timeout=BUILD_TIMEOUT_S, failure="The Docker build failed.")
    if container_port is None:
        exposed = _run(["docker", "image", "inspect", "-f",
                        "{{json .Config.ExposedPorts}}", image]).stdout.strip()
        ports = [p.split("/")[0] for p in (json.loads(exposed or "null") or {})]
        container_port = int(ports[0]) if ports else 80
    _run(["docker", "rm", "-f", key])
    log.add("Starting the app…", flush=True)
    _step(log, ["docker", "run", "-d", "--name", key, *label_args,
                "-p", f"127.0.0.1:{port}:{container_port}", image],
          failure="Docker couldn't start the app.")


def _healthy(url: str) -> bool:
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 400:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(1)
    return False


def _container_ids(key: str) -> list[str]:
    out = _run(["docker", "ps", "-aq", "--filter", f"label={LABEL_DEPLOY}={key}"]).stdout
    return out.split()


def _status(key: str) -> dict:
    out = _run(["docker", "ps", "-a", "--filter", f"label={LABEL_DEPLOY}={key}",
                "--format", "{{.State}}"]).stdout.split()
    if not out:
        return {"status": "stopped"}
    if all(s == "running" for s in out):
        return {"status": "live"}
    return {"status": "crashed",
            "detail": "Part of the app stopped running — open the logs to see why."}


def _logs(key: str) -> list[str]:
    lines: list[str] = []
    for cid in _container_ids(key):
        name = _run(["docker", "inspect", "-f", "{{.Name}}", cid]).stdout.strip().lstrip("/")
        r = _run(["docker", "logs", "--tail", str(LOG_TAIL), cid])
        lines += [f"[{name}] {line}" for line in (r.stdout + r.stderr).splitlines()]
    return lines


def _teardown(key: str) -> None:
    _run(["docker", "compose", "-p", key, "down", "-v", "--remove-orphans",
          "--rmi", "local"], timeout=300)
    for cid in _container_ids(key):
        _run(["docker", "rm", "-f", "-v", cid])
    for kind in ("network", "volume"):
        ids = _run(["docker", kind, "ls", "-q", "--filter",
                    f"label=com.docker.compose.project={key}"]).stdout.split()
        if ids:
            _run(["docker", kind, "rm", *ids])
    _run(["docker", "image", "rm", f"{key}:latest"])
    wd = _find_workdir(key)
    if wd is not None:
        shutil.rmtree(wd, ignore_errors=True)
