"""Tests for ~/.agentira/.env loading."""

from __future__ import annotations

import os
from pathlib import Path


from agentira_cli.state import env_file


def test_parse_env_file_skips_comments_and_export(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\n"
        "export AGENTIRA_DEV_MODE=1\n"
        "AGENTIRA_TEST_API_URL=http://localhost:8111\n"
        "BAD LINE\n"
        'AGENTIRA_TEST_API_KEY="quoted"\n',
        encoding="utf-8",
    )
    assert env_file._parse_env_file(path) == {
        "AGENTIRA_DEV_MODE": "1",
        "AGENTIRA_TEST_API_URL": "http://localhost:8111",
        "AGENTIRA_TEST_API_KEY": "quoted",
    }


def test_shell_env_wins_over_file(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "AGENTIRA_DEV_MODE=0\nAGENTIRA_TEST_API_URL=file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTIRA_DEV_MODE", "1")
    monkeypatch.setenv("AGENTIRA_TEST_API_URL", "shell")

    initial = env_file._snapshot_agentira_env()
    env_file._apply_file_layers(
        env_file._parse_env_file(path), {}, active_differs=False, initial=initial,
    )

    assert os.environ["AGENTIRA_DEV_MODE"] == "1"
    assert os.environ["AGENTIRA_TEST_API_URL"] == "shell"


def test_file_fills_gaps_when_shell_unset(tmp_path: Path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("AGENTIRA_DEV_MODE=0\nAGENTIRA_DAEMON_API_URL=https://prod\n", encoding="utf-8")
    monkeypatch.delenv("AGENTIRA_DEV_MODE", raising=False)
    monkeypatch.delenv("AGENTIRA_DAEMON_API_URL", raising=False)

    initial = env_file._snapshot_agentira_env()
    env_file._apply_file_layers(
        env_file._parse_env_file(path), {}, active_differs=False, initial=initial,
    )

    assert os.environ["AGENTIRA_DEV_MODE"] == "0"
    assert os.environ["AGENTIRA_DAEMON_API_URL"] == "https://prod"


def test_warns_shell_var_missing_from_file():
    warnings = env_file._shell_override_warnings(
        {"AGENTIRA_DEV_MODE": "1"},
        {"AGENTIRA_DAEMON_API_URL": "https://prod"},
        Path.home() / ".agentira" / ".env",
    )
    assert len(warnings) == 1
    assert "AGENTIRA_DEV_MODE" in warnings[0]
    assert ".zshrc" in warnings[0]


def test_warns_shell_overrides_file_value():
    warnings = env_file._shell_override_warnings(
        {"AGENTIRA_DEV_MODE": "1"},
        {"AGENTIRA_DEV_MODE": "0"},
        Path.home() / ".agentira" / ".env",
    )
    assert len(warnings) == 1
    assert "overrides" in warnings[0]


def test_load_cli_env_files_reads_default_and_active_home(tmp_path: Path, monkeypatch):
    default_home = tmp_path / "agentira"
    test_home = tmp_path / "agentira-test"
    default_home.mkdir()
    test_home.mkdir()
    (default_home / ".env").write_text("AGENTIRA_DEV_MODE=0\n", encoding="utf-8")
    (test_home / ".env").write_text(
        "AGENTIRA_DEV_MODE=1\nAGENTIRA_TEST_API_KEY=test-key\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("AGENTIRA_DEV_MODE", raising=False)
    monkeypatch.delenv("AGENTIRA_TEST_API_KEY", raising=False)
    monkeypatch.setenv("AGENTIRA_HOME", str(test_home))
    monkeypatch.setattr(env_file, "_cli_default_home", lambda: default_home)

    env_file.load_cli_env_files()

    assert os.environ["AGENTIRA_DEV_MODE"] == "1"
    assert os.environ["AGENTIRA_TEST_API_KEY"] == "test-key"