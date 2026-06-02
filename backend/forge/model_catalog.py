"""Per-provider model catalog.

Primary source is `model_catalog_data.json` shipped alongside this module.
Cloud instances pick up updates via deploys; self-hosted via `git pull`.
The JSON is refreshed periodically by a developer running
`scripts/refresh_model_catalog.py` (which can talk to provider APIs with
the dev's own keys) — end users never need their own provider API keys
just to see the latest models.

Optional live discovery: if a self-hoster sets ANTHROPIC_API_KEY /
OPENAI_API_KEY / GOOGLE_API_KEY in the server env AND turns on
AGENTIRA_MODEL_CATALOG_LIVE=1, we'll also hit the provider /v1/models
endpoint and merge live ids on top of the shipped list. Off by default
so we don't surprise the user with outbound network calls.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("forge.model_catalog")

_DATA_PATH = Path(__file__).parent / "model_catalog_data.json"

# Which env var holds each provider's discovery key (used only when live
# discovery is opted in). Codex/Claude reuse the API-side key for catalog
# lookup — execution still goes through the CLI session.
API_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "codex": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}

_LIVE_FLAG_ENV = "AGENTIRA_MODEL_CATALOG_LIVE"
_TTL_SECONDS = 6 * 60 * 60  # cache for live-discovery merges

# (models, fetched_at_epoch) per provider — only used when live merge is on.
_live_cache: dict[str, tuple[list[str], float]] = {}
_cache_lock = threading.Lock()

# Shipped catalog loaded once at import time. Reloadable via _reload_data().
_shipped: dict = {}
_shipped_mtime: float = 0.0


def _reload_data() -> None:
    """Read model_catalog_data.json into memory. Cheap; called on import
    and from tests."""
    global _shipped, _shipped_mtime
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            _shipped = json.load(f)
        _shipped_mtime = _DATA_PATH.stat().st_mtime
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        logger.warning("model_catalog_data.json unreadable: %s", exc)
        _shipped = {"providers": {}}
        _shipped_mtime = 0.0


_reload_data()


def shipped_providers() -> dict:
    return _shipped.get("providers", {}) or {}


def known_providers() -> list[str]:
    return list(shipped_providers().keys())


# ── Optional live discovery ──────────────────────────────────────────────

def _http_get_json(url: str, headers: dict[str, str], timeout: float = 8.0) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.info("catalog fetch failed (%s): %s", url, exc)
        return None
    except json.JSONDecodeError as exc:
        logger.info("catalog response not JSON (%s): %s", url, exc)
        return None


def fetch_anthropic(api_key: str) -> list[str] | None:
    """Anthropic /v1/models. Needs a developer API key (claude-code's
    session auth doesn't work here)."""
    if not api_key:
        return None
    data = _http_get_json(
        "https://api.anthropic.com/v1/models?limit=100",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "accept": "application/json",
        },
    )
    if not data:
        return None
    items = data.get("data") or []
    ids = [it.get("id") for it in items if isinstance(it, dict) and it.get("id")]
    return ids or None


def fetch_openai(api_key: str) -> list[str] | None:
    """OpenAI /v1/models. Filters to chat-capable ids by common prefixes
    — raw list includes embeddings, tts, etc."""
    if not api_key:
        return None
    data = _http_get_json(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {api_key}", "accept": "application/json"},
    )
    if not data:
        return None
    items = data.get("data") or []
    keep_prefixes = ("gpt-", "o1", "o3", "o4")
    ids = [
        it["id"] for it in items
        if isinstance(it, dict) and isinstance(it.get("id"), str)
        and it["id"].startswith(keep_prefixes)
    ]
    return ids or None


def fetch_google(api_key: str) -> list[str] | None:
    """Google generativelanguage models, filtered to generateContent-capable."""
    if not api_key:
        return None
    data = _http_get_json(
        f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=200&key={api_key}",
        headers={"accept": "application/json"},
    )
    if not data:
        return None
    items = data.get("models") or []
    ids: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        methods = it.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        name = it.get("name", "")
        if name.startswith("models/"):
            name = name[len("models/"):]
        if name:
            ids.append(name)
    return ids or None


_FETCHERS = {
    "anthropic": fetch_anthropic,
    "claude": fetch_anthropic,
    "openai": fetch_openai,
    "codex": fetch_openai,
    "google": fetch_google,
    "gemini": fetch_google,
}


def _live_enabled() -> bool:
    return os.environ.get(_LIVE_FLAG_ENV, "").lower() in ("1", "true", "yes")


def _merge(live: list[str], shipped: list[str]) -> list[str]:
    """Shipped first (so curated aliases stay at the top of the dropdown);
    then any live ids the shipped list didn't already have."""
    seen = set(shipped)
    merged = list(shipped)
    for m in live:
        if m not in seen:
            merged.append(m)
            seen.add(m)
    return merged


def _live_for(provider: str, refresh: bool) -> list[str] | None:
    """Return live-discovered ids for provider, or None if disabled/failed.
    Cached per-provider with a 6h TTL."""
    if not _live_enabled():
        return None
    fetcher = _FETCHERS.get(provider)
    api_key = os.environ.get(API_KEY_ENV.get(provider, ""), "")
    if not fetcher or not api_key:
        return None

    now = time.time()
    with _cache_lock:
        cached = _live_cache.get(provider)
        if cached and not refresh and now - cached[1] < _TTL_SECONDS:
            return cached[0]

    live = fetcher(api_key)
    if live:
        with _cache_lock:
            _live_cache[provider] = (live, now)
    return live


# ── Public API ───────────────────────────────────────────────────────────

def get_catalog(provider: str, *, refresh: bool = False) -> dict:
    """Catalog entry for one provider.

    Shape: {"provider", "models", "source", "last_updated", "live_enabled",
            "live_merged" (bool — whether live ids were actually merged
            this call)}.

    `source` is "shipped" when only the JSON was used, "live+shipped"
    when live discovery added at least one id on top.
    """
    provider = provider.lower()
    shipped_entry = shipped_providers().get(provider, {})
    shipped_models: list[str] = list(shipped_entry.get("models", []))
    last_updated = shipped_entry.get("last_updated", "")

    live = _live_for(provider, refresh)
    if live:
        merged = _merge(live, shipped_models)
        live_merged = merged != shipped_models
        source = "live+shipped" if live_merged else "shipped"
    else:
        merged = shipped_models
        live_merged = False
        source = "shipped"

    return {
        "provider": provider,
        "models": merged,
        "source": source,
        "last_updated": last_updated,
        "live_enabled": _live_enabled(),
        "live_merged": live_merged,
    }


def get_all_catalogs(*, refresh: bool = False) -> dict:
    return {p: get_catalog(p, refresh=refresh) for p in known_providers()}


def reload_for_tests() -> None:
    _reload_data()
    with _cache_lock:
        _live_cache.clear()
