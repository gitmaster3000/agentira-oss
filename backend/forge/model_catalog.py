"""Dynamic model catalog — per-provider discovery with cached fallbacks.

Goal: agents bound to a runtime (claude-code, codex, gemini, …) should see
the latest models from each provider without us editing a static list every
time a new one ships. Providers expose model-list APIs (Anthropic
/v1/models, OpenAI /v1/models, Google generativelanguage models.list) —
when an API key is available we hit them, cache the result, and fall back
to a curated list otherwise.

claude-code is the awkward case: it authenticates via the user's logged-in
Anthropic session, not a developer API key, so /v1/models discovery only
works if the user separately exports ANTHROPIC_API_KEY (purely for the
catalog lookup, not for execution). We document that and degrade
gracefully — the curated `fallback["anthropic"]` list is the floor.

Cache is in-process, per-provider, with a 6h TTL. POST .../refresh forces
re-fetch. No persistence — the daemon restarts cheaply, and the static
fallback covers a cold start with no network.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("forge.model_catalog")

# Curated fallbacks — minimum the UI should show when discovery is off or
# the network is down. Aliases first (always-latest), then a couple of
# pinned ids so users can reproduce. Keep this small; live discovery is
# the source of truth when it's available.
FALLBACKS: dict[str, list[str]] = {
    "anthropic": [
        "claude-opus-4-7",
        "claude-sonnet-4-7",
        "claude-haiku-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ],
    # claude-code accepts both stable aliases and dated SKUs. Aliases come
    # first so the dropdown defaults to "latest" without users having to
    # re-pick after each Anthropic release.
    "claude": [
        "sonnet",
        "opus",
        "haiku",
        "claude-opus-4-7",
        "claude-sonnet-4-7",
        "claude-haiku-4-7",
        "claude-opus-4-6",
        "claude-sonnet-4-6",
        "claude-haiku-4-6",
        "claude-opus-4-5",
        "claude-sonnet-4-5",
        "claude-haiku-4-5",
    ],
    "openai": [
        "gpt-5",
        "gpt-5-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "o3",
        "o3-mini",
    ],
    "codex": [
        "gpt-5-codex",
        "gpt-5",
        "gpt-5-mini",
        "gpt-4.1",
        "o3",
    ],
    "google": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
    ],
    "gemini": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite-preview",
    ],
}

# Which env var holds each provider's discovery key. Codex/Claude reuse
# the API-side key for catalog lookup only — execution still goes through
# the CLI session.
API_KEY_ENV: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "codex": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}

_TTL_SECONDS = 6 * 60 * 60  # 6h — long enough to avoid hammering the API,
                            # short enough that a new model shows up same day.

# (models, fetched_at_epoch, source) per provider. source ∈ {"live", "fallback"}.
_cache: dict[str, tuple[list[str], float, str]] = {}
_lock = threading.Lock()


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
    """List Anthropic models via /v1/models. Requires a developer API key
    (claude-code's session auth doesn't work here)."""
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
    """List OpenAI models via /v1/models. Filters to chat-capable ids by
    common prefixes — the raw list includes embeddings, tts, etc."""
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
    """List Google generativelanguage models. Filters to those supporting
    generateContent so the dropdown isn't polluted with embedding-only
    SKUs."""
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


def _merge_with_fallback(live: list[str], fallback: list[str]) -> list[str]:
    """Live first, then any fallback ids that aren't already in live. Keeps
    the curated aliases ("sonnet"/"opus"/"haiku") visible even when live
    discovery returns only dated SKUs."""
    seen = set(live)
    merged = list(live)
    for m in fallback:
        if m not in seen:
            merged.append(m)
            seen.add(m)
    return merged


def get_catalog(provider: str, *, refresh: bool = False) -> dict:
    """Return the catalog entry for one provider.

    Shape: {"provider", "models" (list[str]), "source", "fetched_at" (iso),
            "ttl_seconds", "discovery_available" (bool)}.
    source ∈ {"live", "fallback"}. discovery_available is True iff we know
    how to query this provider AND have an API key for it.
    """
    provider = provider.lower()
    fallback = FALLBACKS.get(provider, [])
    fetcher = _FETCHERS.get(provider)
    api_key = os.environ.get(API_KEY_ENV.get(provider, ""), "")

    now = time.time()
    with _lock:
        cached = _cache.get(provider)
        if cached and not refresh:
            models, fetched_at, source = cached
            if now - fetched_at < _TTL_SECONDS:
                return _entry(provider, models, source, fetched_at, fetcher, api_key)

        # Need a fresh read.
        live: list[str] | None = None
        if fetcher and api_key:
            live = fetcher(api_key)

        if live:
            models = _merge_with_fallback(live, fallback)
            source = "live"
        else:
            models = list(fallback)
            source = "fallback"

        _cache[provider] = (models, now, source)
        return _entry(provider, models, source, now, fetcher, api_key)


def _entry(provider: str, models: list[str], source: str, fetched_at: float,
           fetcher, api_key: str) -> dict:
    return {
        "provider": provider,
        "models": models,
        "source": source,
        "fetched_at": datetime.fromtimestamp(fetched_at, tz=timezone.utc).isoformat(),
        "ttl_seconds": _TTL_SECONDS,
        "discovery_available": bool(fetcher and api_key),
    }


def get_all_catalogs(*, refresh: bool = False) -> dict:
    """Return catalogs for every known provider, keyed by provider name."""
    return {p: get_catalog(p, refresh=refresh) for p in FALLBACKS}


def known_providers() -> list[str]:
    return list(FALLBACKS.keys())


def reset_cache_for_tests() -> None:
    """Drop the in-process cache. Tests use this to isolate state."""
    with _lock:
        _cache.clear()
