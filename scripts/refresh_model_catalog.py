"""Refresh backend/forge/model_catalog_data.json from provider APIs.

Run periodically (e.g. weekly CI cron, or by hand when a provider ships
something new). Needs whichever provider keys you have — missing keys
just skip that provider's update and leave its shipped list untouched.

Usage:
    export ANTHROPIC_API_KEY=...
    export OPENAI_API_KEY=...
    export GOOGLE_API_KEY=...
    python -m scripts.refresh_model_catalog
    # then `git diff` to review, commit, and deploy.

Flags:
    --dry-run            print the diff but don't write the file
    --provider <name>    only refresh one provider (anthropic|openai|google
                                                    |claude|codex|gemini)

Curated entries (aliases like "sonnet"/"opus"/"haiku", or pinned ids the
team wants to preserve) are kept by staying at the top — live ids are
merged AFTER the existing list, so manual additions survive a refresh.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from backend.forge import model_catalog

DATA_PATH = Path(__file__).resolve().parent.parent / "backend" / "forge" / "model_catalog_data.json"


# (provider, fetcher, env var). claude/codex/gemini map to the same API
# as anthropic/openai/google for catalog purposes.
PROVIDERS = [
    ("anthropic", model_catalog.fetch_anthropic, "ANTHROPIC_API_KEY"),
    ("claude",    model_catalog.fetch_anthropic, "ANTHROPIC_API_KEY"),
    ("openai",    model_catalog.fetch_openai,    "OPENAI_API_KEY"),
    ("codex",     model_catalog.fetch_openai,    "OPENAI_API_KEY"),
    ("google",    model_catalog.fetch_google,    "GOOGLE_API_KEY"),
    ("gemini",    model_catalog.fetch_google,    "GOOGLE_API_KEY"),
]


def _load() -> dict:
    return json.loads(DATA_PATH.read_text())


def _save(data: dict) -> None:
    DATA_PATH.write_text(json.dumps(data, indent=2) + "\n")


def _merge_keep_existing(existing: list[str], live: list[str]) -> list[str]:
    """Keep existing order/entries intact; append live ids the JSON didn't have."""
    seen = set(existing)
    out = list(existing)
    for m in live:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


def refresh(only: str | None = None, dry_run: bool = False) -> int:
    data = _load()
    providers = data.setdefault("providers", {})
    today = date.today().isoformat()
    changed = 0

    for name, fetcher, env in PROVIDERS:
        if only and name != only:
            continue
        api_key = os.environ.get(env, "")
        if not api_key:
            print(f"skip  {name:10s}  no {env} set")
            continue
        live = fetcher(api_key)
        if not live:
            print(f"skip  {name:10s}  fetch failed or returned empty")
            continue

        entry = providers.setdefault(name, {"models": [], "last_updated": today})
        before = list(entry.get("models", []))
        after = _merge_keep_existing(before, live)
        added = [m for m in after if m not in before]

        if added:
            entry["models"] = after
            entry["last_updated"] = today
            changed += 1
            print(f"ok    {name:10s}  +{len(added)}: {added}")
        else:
            # No new ids — but bump last_updated so freshness is visible.
            entry["last_updated"] = today
            print(f"ok    {name:10s}  no new models")

    if dry_run:
        print("\n--- dry-run: not writing file ---")
        print(json.dumps(data, indent=2))
        return 0

    _save(data)
    print(f"\nwrote {DATA_PATH}  ({changed} provider(s) gained new models)")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--provider", default=None)
    args = p.parse_args(argv)
    return refresh(only=args.provider, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
