"""GitHub release check + semver helpers for daemon self-update."""

from __future__ import annotations

import json
from unittest import mock

from agentira_cli.update_check import (
    TAG_PREFIX,
    check_for_update,
    fetch_latest_cli_release,
    is_newer,
    parse_version,
    run_update,
    should_check_now,
)


def test_parse_version_and_compare():
    assert parse_version("0.1.10") > parse_version("0.1.9")
    assert parse_version("v1.0.0") == (1, 0, 0)
    assert parse_version(f"{TAG_PREFIX}0.2.0") == (0, 2, 0)
    assert is_newer("0.2.0", "0.1.9")
    assert not is_newer("0.1.0", "0.1.0")


def test_fetch_latest_cli_release_picks_newest_tag():
    payload = [
        {
            "tag_name": "agentira-cli-v0.1.0",
            "draft": False, "prerelease": False,
            "name": "CLI 0.1.0",
            "html_url": "https://github.com/o/r/releases/tag/agentira-cli-v0.1.0",
            "assets": [{"name": "agentira_cli-0.1.0-py3-none-any.whl",
                        "browser_download_url": "https://ex/wheel.whl"}],
        },
        {
            "tag_name": "v1.0.0-backend",
            "draft": False, "prerelease": False,
            "assets": [],
        },
        {
            "tag_name": "agentira-cli-v0.2.0",
            "draft": False, "prerelease": False,
            "name": "CLI 0.2.0",
            "html_url": "https://github.com/o/r/releases/tag/agentira-cli-v0.2.0",
            "assets": [],
        },
    ]
    with mock.patch("agentira_cli.update_check._api_get", return_value=payload):
        rel = fetch_latest_cli_release(repo="o/r")
    assert rel is not None
    assert rel.version == "0.2.0"
    assert "0.2.0" in rel.install_spec or "agentira-cli-v0.2.0" in rel.install_spec


def test_check_for_update_reports_pending():
    payload = [{
        "tag_name": "agentira-cli-v9.0.0",
        "draft": False, "prerelease": False,
        "html_url": "https://ex", "assets": [],
    }]
    with mock.patch("agentira_cli.update_check._api_get", return_value=payload):
        cur, pending = check_for_update(current="0.1.0")
    assert cur == "0.1.0"
    assert pending is not None
    assert pending.version == "9.0.0"


def test_run_update_check_only():
    payload = [{
        "tag_name": "agentira-cli-v0.3.0",
        "draft": False, "prerelease": False,
        "html_url": "https://ex", "assets": [],
    }]
    with mock.patch("agentira_cli.update_check._api_get", return_value=payload):
        out = run_update(check_only=True)
    assert out["latest"] == "0.3.0"
    assert "update" in out["message"].lower()


def test_should_check_respects_skip_env(tmp_path, monkeypatch):
    cache = tmp_path / "update_check.json"
    cache.write_text(json.dumps({"checked_at": 1e12}))
    monkeypatch.setenv("AGENTIRA_SKIP_UPDATE_CHECK", "1")
    assert not should_check_now(cache, interval_hours=24)
    monkeypatch.delenv("AGENTIRA_SKIP_UPDATE_CHECK", raising=False)
    assert not should_check_now(cache, interval_hours=24)