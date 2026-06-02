"""AP-157: workspace-default agent templates.

Templates live under `data/templates/agents/` as YAML + Markdown pairs.
The yaml carries structural config (name, model, mcp_servers, flags);
the sibling .md (same basename) holds the system_prompt content.

The split is the prompts-as-config principle in practice:
- YAML is data
- Markdown is prose
- Both live OUTSIDE Python service code
- Each lands on a user-editable Profile field via set-if-empty
- After first seed, the user owns every edit; code never re-stamps

Adding a new template = drop `name.yaml` + `name.md` into the dir;
the next call to `seed_all()` picks them up.

Author's note: this module is intentionally small. The clever stuff is
in the templates themselves; the loader's job is "read files, persist
fields that are still empty." Functions, not classes.
"""

from __future__ import annotations

import json as _json
import logging
import secrets
from pathlib import Path
from typing import Any

import yaml

from backend.db import SessionLocal
from backend.models import Profile, Role


logger = logging.getLogger("agentira.agent_templates")


_TEMPLATES_DIR = (
    Path(__file__).resolve().parent.parent / "templates" / "agents"
)


def _read_template(yaml_path: Path) -> dict[str, Any] | None:
    """Parse a single yaml+md pair. Returns the merged dict or None
    if the file is invalid or missing a `name`."""
    try:
        raw = yaml_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("template parse failed %s: %s", yaml_path, exc)
        return None
    if not isinstance(data, dict) or not data.get("name"):
        logger.warning("template missing name: %s", yaml_path)
        return None
    # Pull the system prompt from a sibling .md (same basename) if the
    # yaml doesn't carry it inline. Markdown is the canonical way; inline
    # in yaml is allowed for trivial cases.
    if "system_prompt" not in data:
        md = yaml_path.with_suffix(".md")
        if md.exists():
            try:
                data["system_prompt"] = md.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("template prompt read failed %s: %s", md, exc)
    return data


def discover() -> list[dict[str, Any]]:
    """All valid templates found on disk, sorted by filename."""
    if not _TEMPLATES_DIR.exists():
        return []
    out: list[dict[str, Any]] = []
    for yaml_path in sorted(_TEMPLATES_DIR.glob("*.yaml")):
        t = _read_template(yaml_path)
        if t:
            out.append(t)
    return out


def get_template(name: str) -> dict[str, Any] | None:
    for t in discover():
        if t.get("name") == name:
            return t
    return None


def seed_all() -> dict[str, list[str]]:
    """Set-if-empty seed every template as a Profile.

    Idempotent: on a second call, profiles that already exist are left
    alone (we don't even touch the field-level set-if-empty, since
    they're already past-first-create). Only fresh-create paths fill
    the seed fields, mirroring the Conductor's "code seeds once,
    user owns forever after" contract.

    Returns counts for telemetry: created / already_present /
    seeded_fields (a list of (name, field) pairs for the first-touch
    fills).
    """
    out: dict[str, list[str]] = {
        "created": [],
        "already_present": [],
        "seeded_fields": [],
    }
    with SessionLocal() as db:
        bot_role = db.query(Role).filter(Role.name == "bot").first()
        if not bot_role:
            # Roles haven't been seeded yet — caller will retry later.
            return out

        for t in discover():
            name = t["name"]
            prof = db.query(Profile).filter(Profile.name == name).first()
            is_new = prof is None
            if is_new:
                prof = Profile(
                    name=name,
                    display_name=t.get("display_name", name),
                    password_hash="",
                    avatar_url="",
                    webhook_url="",
                    role_id=bot_role.id,
                    api_key=secrets.token_hex(32),
                )
                db.add(prof)
                db.flush()
                out["created"].append(name)
                logger.info("seeded agent template profile: %s", name)
            else:
                out["already_present"].append(name)

            _apply_set_if_empty(prof, t, out)
        db.commit()
    return out


def _apply_set_if_empty(prof: Profile, t: dict[str, Any],
                        out: dict[str, list[str]]) -> None:
    """Fill any field on the profile that's still empty. Never overwrites
    a user-edited value — that's the prompts-as-config contract.

    `is_system` is the exception: it's structural (Conductor is the
    workspace singleton; the others are not), so code keeps authority.
    """
    name = prof.name

    def _seed_if_empty(field: str, value: Any) -> None:
        current = getattr(prof, field, None)
        if value is None:
            return
        # "empty" means None or "" for strings; the user typing a value
        # already lands it on the row and stops us from re-stamping.
        if current in (None, "", b""):
            setattr(prof, field, value)
            out["seeded_fields"].append(f"{name}:{field}")

    _seed_if_empty("system_prompt", t.get("system_prompt"))
    _seed_if_empty("model", t.get("model"))
    _seed_if_empty("personality", t.get("personality"))

    mcp = t.get("mcp_servers")
    if mcp and not prof.mcp_servers:
        prof.mcp_servers = _json.dumps(list(mcp))
        out["seeded_fields"].append(f"{name}:mcp_servers")

    # is_system is code-authoritative — keeps the Conductor protected
    # against accidental deletion even if a user toggled it off in a
    # past session. Other templates default to False (regular agents).
    desired_is_system = bool(t.get("is_system", False))
    if prof.is_system != desired_is_system:
        prof.is_system = desired_is_system

    # Conductor-only cadence config — only mirror on first create, the
    # same set-if-empty rule applies.
    for cad_field in (
        "conductor_active",
        "conductor_tick_seconds",
        "conductor_plan_interval_minutes",
        "conductor_report_time",
        "conductor_report_enabled",
        "conductor_enabled",
        "max_concurrent_runs",
    ):
        if cad_field not in t:
            continue
        # These are scalar columns; "empty" for booleans is the column
        # default. We only touch them on the brand-new-profile path
        # (the `out["created"]` check covers that — if we're past first
        # create we don't sync code-side cadence onto user edits).
        if name in out["created"]:
            setattr(prof, cad_field, t[cad_field])
