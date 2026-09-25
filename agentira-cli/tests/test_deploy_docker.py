"""Local Docker deploy — the daemon half.

Unit tests cover input sanitizing and naming. The `real_docker` tests run the
actual `docker` / `docker compose` CLI against tiny fixture apps committed to a
throwaway git repo (file:// remote): deploy → preview answers 200 → redeploy a
new ref → teardown leaves no labelled container behind. They skip cleanly when
Docker isn't available.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path

import pytest

from agentira_cli.daemon import deploy as dd

FIXTURES = Path(__file__).parent / "fixtures"


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True,
                              timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        return False


real_docker = pytest.mark.skipif(not _docker_ok(), reason="docker not available")


class Reporter:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **fields):
        self.calls.append(fields)

    @property
    def last(self) -> dict:
        return self.calls[-1]


def _git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _repo(tmp_path: Path, fixture: str) -> tuple[str, Path]:
    """A bare 'remote' seeded with the fixture on main. Returns (url, work)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    work = tmp_path / "work"
    shutil.copytree(FIXTURES / fixture, work)
    _git(work, "init", "-q", "-b", "main")
    _git(work, "add", "-A")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
    _git(work, "remote", "add", "origin", f"file://{remote}")
    _git(work, "push", "-q", "origin", "main")
    return f"file://{remote}", work


def _frame(action, handle, **extra):
    return {"type": "deploy", "action": action, "deployment_id": handle, **extra}


def _get(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, resp.read().decode()


def _labelled(key: str) -> str:
    return subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label={dd.LABEL_DEPLOY}={key}"],
        capture_output=True, text=True).stdout.strip()


@pytest.fixture
def deploys_dir(tmp_path, monkeypatch):
    d = tmp_path / "deploys"
    monkeypatch.setattr(dd, "DEPLOYS_DIR", d)
    return d


# ── sanitizing / naming (no docker needed) ────────────────────────────────

@pytest.mark.parametrize("bad", [
    "main; rm -rf /", "--upload-pack=touch /tmp/x", "a/../../b", "$(id)",
    "`id`", "a b", "", "-x", "x\ny", "branch|cat",
])
def test_hostile_refs_are_rejected(bad):
    with pytest.raises(ValueError):
        dd.validate_ref(bad)


@pytest.mark.parametrize("bad", ["ext::sh -c touch% /tmp/x", "-oProxyCommand=x", "", "/etc"])
def test_hostile_source_urls_are_rejected(bad):
    with pytest.raises(ValueError):
        dd.validate_source_url(bad)


def test_hostile_frame_reports_failure_without_running_anything(deploys_dir, monkeypatch):
    ran = []
    monkeypatch.setattr(dd, "_run", lambda *a, **k: ran.append(a))
    report = Reporter()
    dd.handle(_frame("deploy", "rt1:agentira-x-0123456789", project_id="p1",
                     branch="main; rm -rf /", ref="main; rm -rf /",
                     source_url="file:///tmp/nope", config={}), report)
    assert ran == []
    assert report.last["status"] == "failed"
    assert not deploys_dir.exists()


def test_hostile_handle_is_rejected(deploys_dir, monkeypatch):
    ran = []
    monkeypatch.setattr(dd, "_run", lambda *a, **k: ran.append(a))
    report = Reporter()
    dd.handle(_frame("teardown", "rt1:agentira-x; docker rm -f $(docker ps -aq)"), report)
    assert ran == []
    assert report.last["status"] == "failed"


def test_host_port_is_deterministic_and_in_range():
    a = dd.preferred_port("agentira-main-0123456789")
    assert a == dd.preferred_port("agentira-main-0123456789")
    assert dd.PORT_RANGE[0] <= a < dd.PORT_RANGE[1]
    assert a != dd.preferred_port("agentira-main-9876543210")


def test_workdir_is_daemon_owned(deploys_dir):
    wd = dd.workdir("p1", "agentira-feature-cart-0123456789")
    assert wd == deploys_dir / "p1" / "feature-cart-0123456789"


# ── real docker ──────────────────────────────────────────────────────────

@real_docker
def test_single_container_deploy_redeploy_teardown(tmp_path, deploys_dir):
    url, work = _repo(tmp_path, "deploy_single")
    key = "agentira-main-a1b2c3d4e5"
    handle = f"rt1:{key}"
    report = Reporter()
    try:
        dd.handle(_frame("deploy", handle, project_id="proj-1", branch="main",
                         ref="main", source_url=url, config={}), report)
        assert report.last["status"] == "live", report.last
        assert any(c.get("status") == "building" for c in report.calls)
        preview = report.last["url"]
        assert preview.startswith("http://127.0.0.1:")
        code, body = _get(preview)
        assert code == 200 and "fixture v1" in body
        assert (deploys_dir / "proj-1" / "main-a1b2c3d4e5" / "src").is_dir()

        # Redeploy a new ref of the same branch: same URL, new content.
        (work / "index.html").write_text("<html><body>deploy fixture v2</body></html>\n")
        _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "v2")
        _git(work, "push", "-q", "origin", "main")
        dd.handle(_frame("deploy", handle, project_id="proj-1", branch="main",
                         ref="main", source_url=url, config={}), report)
        assert report.last["status"] == "live", report.last
        assert report.last["url"] == preview
        assert "fixture v2" in _get(preview)[1]

        dd.handle(_frame("status", handle), report)
        assert report.last["status"] == "live"
        dd.handle(_frame("logs", handle), report)
        assert any("GET /" in line for line in report.last["logs"])
    finally:
        dd.handle(_frame("teardown", handle), report)
    assert report.last["status"] == "stopped"
    assert _labelled(key) == ""
    assert not (deploys_dir / "proj-1" / "main-a1b2c3d4e5").exists()


@real_docker
def test_compose_two_services_deploy_and_teardown(tmp_path, deploys_dir):
    url, _work = _repo(tmp_path, "deploy_compose")
    key = "agentira-feature-x-f0e1d2c3b4"
    handle = f"rt1:{key}"
    report = Reporter()
    try:
        dd.handle(_frame("deploy", handle, project_id="proj-2", branch="feature/x",
                         ref="main", source_url=url, config={}), report)
        assert report.last["status"] == "live", report.last
        code, body = _get(report.last["url"])
        assert code == 200 and "api says hello" in body
        # Every container of the compose app is labelled for teardown.
        assert len(_labelled(key).split()) == 2
        # The fixed 8080 in the compose file was remapped, not published.
        assert not report.last["url"].endswith(":8080")
    finally:
        dd.handle(_frame("teardown", handle), report)
    assert _labelled(key) == ""
    leftover = subprocess.run(
        ["docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={key}"],
        capture_output=True, text=True).stdout.strip()
    assert leftover == ""


# ── daemon wiring: frame → handler → result POST ─────────────────────────

def test_daemon_deploy_frame_posts_results_back(monkeypatch):
    from unittest.mock import MagicMock
    from agentira_cli.daemon import core
    d = core.AgentiraDaemon.__new__(core.AgentiraDaemon)
    d.client, d._daemon_id = MagicMock(), "d1"

    class _SyncThread:
        def __init__(self, target, daemon=None):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(core.threading, "Thread", _SyncThread)
    monkeypatch.setattr(dd, "_status", lambda key: {"status": "live"})

    d._deploy(_frame("status", "rt1:agentira-main-0123456789"))
    kw = d.client.post_deploy_result.call_args.kwargs
    assert kw == {"daemon_id": "d1", "deployment_id": "rt1:agentira-main-0123456789",
                  "action": "status", "status": "live"}
