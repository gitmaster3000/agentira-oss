"""Backend-hosted release check + semver helpers for daemon self-update."""

from __future__ import annotations

import json
import urllib.error
from unittest import mock

from agentira_cli.update_check import (
    check_for_update,
    fetch_latest_cli_release,
    is_newer,
    parse_version,
    run_update,
    should_check_now,
)

API = "https://agentira.example.com"
PAYLOAD = {
    "version": "0.3.0",
    "min_python": "3.11",
    "install_url": "https://agentira.example.com/api/public/cli/wheels/agentira_cli-0.3.0-py3-none-any.whl",
    "install_sh_url": "https://agentira.example.com/api/public/install.sh",
}


def test_parse_version_and_compare():
    assert parse_version("0.1.10") > parse_version("0.1.9")
    assert parse_version("v1.0.0") == (1, 0, 0)
    assert is_newer("0.2.0", "0.1.9")
    assert not is_newer("0.1.0", "0.1.0")


def test_fetch_latest_cli_release_from_backend():
    with mock.patch("agentira_cli.update_check._fetch_release_json", return_value=PAYLOAD):
        rel = fetch_latest_cli_release(api_url=API)
    assert rel is not None
    assert rel.version == "0.3.0"
    assert rel.install_spec.endswith(".whl")


def test_check_for_update_reports_pending():
    with mock.patch("agentira_cli.update_check._fetch_release_json", return_value=PAYLOAD):
        cur, pending, status = check_for_update(api_url=API, current="0.1.0")
    assert cur == "0.1.0"
    assert status == "ok"
    assert pending is not None
    assert pending.version == "0.3.0"


def test_run_update_check_only():
    with mock.patch("agentira_cli.update_check._fetch_release_json", return_value=PAYLOAD):
        out = run_update(api_url=API, check_only=True)
    assert out["latest"] == "0.3.0"
    assert "update" in out["message"].lower()


def test_should_check_respects_skip_env(tmp_path, monkeypatch):
    cache = tmp_path / "update_check.json"
    cache.write_text(json.dumps({"checked_at": 1e12}))
    monkeypatch.setenv("AGENTIRA_SKIP_UPDATE_CHECK", "1")
    assert not should_check_now(cache, interval_hours=24)
    monkeypatch.delenv("AGENTIRA_SKIP_UPDATE_CHECK", raising=False)
    assert not should_check_now(cache, interval_hours=24)


def test_run_update_not_available_on_404():
    err = urllib.error.HTTPError(
        f"{API}/api/public/cli-release", 404, "Not Found", {}, None,
    )
    with mock.patch("agentira_cli.update_check._fetch_release_json", side_effect=err):
        out = run_update(api_url=API, check_only=True)
    assert out["latest"] is None
    assert "no cli release" in out["message"].lower()


def test_run_update_unreachable_on_network_error():
    with mock.patch(
        "agentira_cli.update_check._fetch_release_json",
        side_effect=urllib.error.URLError("timed out"),
    ):
        out = run_update(api_url=API, check_only=True)
    assert out["latest"] is None
    assert "could not reach" in out["message"].lower()