"""Tests for backend.forge.model_catalog.

Primary source is the shipped model_catalog_data.json. Live discovery
is opt-in via AGENTIRA_MODEL_CATALOG_LIVE + a provider API key, and
merges live ids on top of the shipped list.
"""

import json
from pathlib import Path

import pytest

from backend.forge import model_catalog


@pytest.fixture(autouse=True)
def _reset():
    model_catalog.reload_for_tests()
    yield
    model_catalog.reload_for_tests()


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                "AGENTIRA_MODEL_CATALOG_LIVE"):
        monkeypatch.delenv(env, raising=False)


def test_shipped_catalog_loaded_for_every_provider():
    """End users see the shipped JSON with no env config at all."""
    catalogs = model_catalog.get_all_catalogs()
    assert set(catalogs.keys()) >= {
        "anthropic", "claude", "openai", "codex", "google", "gemini",
    }
    for name, entry in catalogs.items():
        assert entry["source"] == "shipped", name
        assert entry["models"], f"{name} shipped list must be non-empty"
        assert entry["last_updated"], f"{name} must carry a freshness date"
        assert entry["live_enabled"] is False
        assert entry["live_merged"] is False


def test_live_disabled_even_with_api_key(monkeypatch):
    """API key alone doesn't trigger live discovery — the live flag must
    also be opted in. Keeps outbound traffic off by default."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    called = {"n": 0}
    monkeypatch.setitem(
        model_catalog._FETCHERS,
        "anthropic",
        lambda k: (called.__setitem__("n", called["n"] + 1) or ["x"]),
    )
    entry = model_catalog.get_catalog("anthropic")
    assert called["n"] == 0
    assert entry["source"] == "shipped"
    assert entry["live_enabled"] is False


def test_live_merge_when_flag_and_key_set(monkeypatch):
    """With AGENTIRA_MODEL_CATALOG_LIVE=1 + key present, live ids merge
    on top of shipped (shipped order preserved, then live extras)."""
    monkeypatch.setenv("AGENTIRA_MODEL_CATALOG_LIVE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.setitem(
        model_catalog._FETCHERS,
        "anthropic",
        lambda k: ["claude-opus-4-7", "brand-new-future-model"],
    )
    entry = model_catalog.get_catalog("anthropic")
    assert entry["source"] == "live+shipped"
    assert entry["live_merged"] is True
    # Shipped models come first (curated aliases stay at the top).
    assert entry["models"][0] == "claude-opus-4-7"
    # Live-only id is appended.
    assert "brand-new-future-model" in entry["models"]
    # No duplicates.
    assert len(entry["models"]) == len(set(entry["models"]))


def test_live_failure_returns_shipped(monkeypatch):
    """When live discovery is on but the fetch fails, the response is
    pure shipped — never empty, never errors."""
    monkeypatch.setenv("AGENTIRA_MODEL_CATALOG_LIVE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setitem(model_catalog._FETCHERS, "openai", lambda k: None)
    entry = model_catalog.get_catalog("openai")
    assert entry["source"] == "shipped"
    assert entry["models"] == model_catalog.shipped_providers()["openai"]["models"]


def test_unknown_provider_returns_empty_shipped():
    entry = model_catalog.get_catalog("not-a-provider")
    assert entry["models"] == []
    assert entry["source"] == "shipped"
    assert entry["last_updated"] == ""


def test_shipped_json_well_formed():
    """Regression guard for the data file: every entry has the required
    shape, last_updated is a parseable date, no duplicate model ids."""
    path = Path(__file__).resolve().parent.parent / "backend" / "forge" / "model_catalog_data.json"
    data = json.loads(path.read_text())
    assert data.get("schema_version") == 1
    providers = data.get("providers") or {}
    assert providers, "model_catalog_data.json must define providers"
    for name, entry in providers.items():
        models = entry.get("models", [])
        assert isinstance(models, list) and models, f"{name} has no models"
        assert len(models) == len(set(models)), f"{name} has duplicate ids"
        last = entry.get("last_updated", "")
        # YYYY-MM-DD
        assert len(last) == 10 and last[4] == "-" and last[7] == "-", \
            f"{name}.last_updated must be ISO date, got {last!r}"
