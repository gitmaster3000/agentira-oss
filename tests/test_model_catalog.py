"""Tests for backend.forge.model_catalog — dynamic model discovery.

The catalog merges live provider /v1/models output with a curated fallback
list, caches per-provider in process, and serves a fallback when no API
key is configured. These tests pin that behavior without hitting the
network.
"""

import pytest

from backend.forge import model_catalog


@pytest.fixture(autouse=True)
def _reset_cache():
    model_catalog.reset_cache_for_tests()
    yield
    model_catalog.reset_cache_for_tests()


def test_fallback_when_no_api_key(monkeypatch):
    """Without an API key, every provider serves its curated fallback so
    the UI dropdown is never empty."""
    for env in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    catalogs = model_catalog.get_all_catalogs()
    for name, entry in catalogs.items():
        assert entry["source"] == "fallback", name
        assert entry["models"], f"{name} fallback must be non-empty"
        assert entry["discovery_available"] is False


def test_live_fetch_merged_with_fallback(monkeypatch):
    """When live discovery returns ids, they appear first; fallback ids
    not in the live response are appended so curated aliases survive."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")

    def fake_fetch(api_key):
        assert api_key == "fake"
        return ["claude-opus-4-7", "claude-sonnet-4-7", "brand-new-model"]

    monkeypatch.setattr(model_catalog, "fetch_anthropic", fake_fetch)
    monkeypatch.setitem(model_catalog._FETCHERS, "anthropic", fake_fetch)

    entry = model_catalog.get_catalog("anthropic")
    assert entry["source"] == "live"
    assert entry["discovery_available"] is True
    # Live first
    assert entry["models"][:3] == ["claude-opus-4-7", "claude-sonnet-4-7", "brand-new-model"]
    # Fallback ids that weren't in live still present (e.g. claude-haiku-4-7)
    assert "claude-haiku-4-7" in entry["models"]
    # No duplicates
    assert len(entry["models"]) == len(set(entry["models"]))


def test_live_failure_falls_back(monkeypatch):
    """If the live fetcher returns None (network error / 401), we serve
    fallback rather than an empty list."""
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setitem(model_catalog._FETCHERS, "openai", lambda key: None)
    entry = model_catalog.get_catalog("openai")
    assert entry["source"] == "fallback"
    assert entry["models"] == model_catalog.FALLBACKS["openai"]


def test_cache_hits_within_ttl(monkeypatch):
    """A second call within TTL must not re-invoke the live fetcher."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    calls = {"n": 0}

    def fake_fetch(api_key):
        calls["n"] += 1
        return ["claude-opus-4-7"]

    monkeypatch.setitem(model_catalog._FETCHERS, "anthropic", fake_fetch)
    model_catalog.get_catalog("anthropic")
    model_catalog.get_catalog("anthropic")
    assert calls["n"] == 1


def test_refresh_bypasses_cache(monkeypatch):
    """refresh=True forces a re-fetch even when the cache is warm."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    calls = {"n": 0}

    def fake_fetch(api_key):
        calls["n"] += 1
        return ["claude-opus-4-7"]

    monkeypatch.setitem(model_catalog._FETCHERS, "anthropic", fake_fetch)
    model_catalog.get_catalog("anthropic")
    model_catalog.get_catalog("anthropic", refresh=True)
    assert calls["n"] == 2


def test_unknown_provider_returns_empty_fallback():
    entry = model_catalog.get_catalog("unknown-provider")
    assert entry["models"] == []
    assert entry["source"] == "fallback"


def test_known_providers_covers_claude_codex_gemini():
    """Regression guard: claude-code + codex + gemini runtimes need a
    catalog entry or the agent-create dropdown will be empty."""
    providers = set(model_catalog.known_providers())
    assert {"claude", "codex", "gemini", "anthropic", "openai", "google"} <= providers
