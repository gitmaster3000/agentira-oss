"""WFE Phase 2 (plan v4 §10 + §5): the verified-evidence provider registry.

A gate that decides whether work moves FORWARD must stand on a *fact fetched
from a trusted source*, not on text an agent wrote about itself. This module
is where those facts come from.

A **provider** owns a namespace (`github_pr`, `ci`, `commit`, `human_approval`),
declares a typed `schema`, a `ttl_seconds`, and a `fetch()` that reads its fact
using PLATFORM credentials (the org GitHub App) — never an agent's token. The
result is a typed `Evidence` value:

  - **present** — the fact was established; `data` holds the typed fields.
  - **absent**  — the fact could NOT be established (missing creds, API error,
    no verdict recorded yet). Absent is a first-class value, not an exception:
    a terminal gate treats absent as a BLOCK. Evidence never *allows* by
    default — silence is not approval (the 2026-07-04 incident: a clean run
    was read as merge approval).

`snapshot()` evaluates a set of namespaces once and returns a JSON-serializable
dict; the driver persists it on the `gate_evaluations` row so a block can be
explained after the fact from exactly what was read (plan v4 §5).

Quantitative facts use a named-check convention: `evidence.check("build")` on a
`ci` Evidence resolves one named check without the caller re-parsing `data`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger("agentira.evidence")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── The typed value ──────────────────────────────────────────────────────

@dataclass
class Evidence:
    """One provider's verdict for one task at one moment.

    `present=False` (absent) means the fact could not be established — a
    terminal gate must BLOCK on it. Construct via `Evidence.of(...)` /
    `Evidence.absent(...)`, never by trusting a default."""
    namespace: str
    present: bool
    data: dict = field(default_factory=dict)
    reason: str = ""
    source: str = ""
    fetched_at: datetime | None = None

    @classmethod
    def of(cls, namespace: str, data: dict, *, source: str) -> "Evidence":
        return cls(namespace=namespace, present=True, data=dict(data),
                   source=source, fetched_at=_utcnow())

    @classmethod
    def absent(cls, namespace: str, reason: str, *, source: str = "") -> "Evidence":
        return cls(namespace=namespace, present=False, reason=reason,
                   source=source, fetched_at=_utcnow())

    def check(self, name: str) -> dict | None:
        """Named-check convention for quantitative providers (`ci`).

        Returns the named check's record (e.g. `{"conclusion": "success"}`)
        or None when the evidence is absent or the check is missing — the
        caller decides what a missing check means for its gate."""
        if not self.present:
            return None
        return (self.data.get("checks") or {}).get(name)

    def passed(self, name: str) -> bool:
        """True iff the named check is present AND concluded successfully."""
        rec = self.check(name)
        return bool(rec) and rec.get("conclusion") == "success"

    def to_dict(self) -> dict:
        """JSON-serializable form for the gate_evaluations snapshot."""
        return {
            "namespace": self.namespace,
            "present": self.present,
            "data": self.data,
            "reason": self.reason,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


# ── Provider registry ────────────────────────────────────────────────────

@dataclass
class Provider:
    namespace: str
    ttl_seconds: int
    schema: dict           # {field: "type"} — the shape of a present `data`
    fetch: Callable[..., Evidence]   # (task, db, ctx) -> Evidence


_REGISTRY: dict[str, Provider] = {}
# Per-(namespace, task_id) TTL cache so one evaluation pass doesn't hit an
# external API twice. Keyed value: (fetched_monotonic_ok datetime, Evidence).
_CACHE: dict[tuple[str, str], tuple[datetime, Evidence]] = {}


def register(provider: Provider) -> None:
    _REGISTRY[provider.namespace] = provider


def get(namespace: str) -> Provider | None:
    return _REGISTRY.get(namespace)


def namespaces() -> list[str]:
    return sorted(_REGISTRY)


def evaluate(namespace: str, task, db, *, ctx: dict | None = None,
             use_cache: bool = False) -> Evidence:
    """Fetch `namespace` evidence for `task`. Never raises: a provider that
    throws yields typed-absent (which blocks), so a flaky API can't be
    mistaken for approval."""
    prov = _REGISTRY.get(namespace)
    if prov is None:
        return Evidence.absent(namespace, f"no provider registered for '{namespace}'")
    key = (namespace, getattr(task, "id", "") or "")
    if use_cache and key in _CACHE:
        at, ev = _CACHE[key]
        if (_utcnow() - at).total_seconds() < prov.ttl_seconds:
            return ev
    try:
        ev = prov.fetch(task, db, ctx or {})
    except Exception as e:  # noqa: BLE001 — absence, not a crash, is the contract
        logger.warning("evidence: provider %s raised, treating as absent: %s",
                       namespace, e)
        ev = Evidence.absent(namespace, f"fetch error: {e}")
    _CACHE[key] = (_utcnow(), ev)
    return ev


def snapshot(namespaces_: list[str], task, db, *,
             ctx: dict | None = None) -> dict:
    """Evaluate each namespace once; return a JSON-serializable dict keyed by
    namespace. This is what gets persisted on the gate_evaluations row."""
    return {ns: evaluate(ns, task, db, ctx=ctx).to_dict() for ns in namespaces_}


# ── Platform GitHub credentials (org App — never an agent token) ──────────

def _platform_github():
    """Return an authenticated org-GitHub-App accessor, or None when the
    platform App isn't configured yet. Providers that read remote git state
    return typed-absent (block) when this is None — remote facts are never
    assumed true. Wiring the App is a later slice; the seam lives here so
    the providers don't reach for an agent's token as a fallback."""
    if not os.environ.get("AGENTIRA_GITHUB_APP_ID"):
        return None
    # Real installation-token exchange lands with the CI/CD wiring (AP-159).
    return None


# ── Providers ────────────────────────────────────────────────────────────

def _fetch_github_pr(task, db, ctx: dict) -> Evidence:
    gh = _platform_github()
    if gh is None:
        return Evidence.absent(
            "github_pr", "org GitHub App not configured — PR state unverifiable",
            source="github_app")
    return Evidence.absent("github_pr", "not implemented", source="github_app")


def _fetch_ci(task, db, ctx: dict) -> Evidence:
    gh = _platform_github()
    if gh is None:
        return Evidence.absent(
            "ci", "org GitHub App not configured — CI checks unverifiable",
            source="github_app")
    return Evidence.absent("ci", "not implemented", source="github_app")


def _fetch_commit(task, db, ctx: dict) -> Evidence:
    gh = _platform_github()
    if gh is None:
        return Evidence.absent(
            "commit", "org GitHub App not configured — commit unverifiable",
            source="github_app")
    return Evidence.absent("commit", "not implemented", source="github_app")


def _fetch_human_approval(task, db, ctx: dict) -> Evidence:
    """A reviewer's APPROVE verdict — recorded as a TYPED review_verdict row
    (not a string-matched comment). `ctx` narrows it to the specific review:
      reviewer: the reviewer profile name (server-injected `Activity.actor`,
                not prompt-writable) whose verdict counts.
      since:    only verdicts recorded at/after this instant (the review run's
                start) count — a stale approval from a prior cycle doesn't
                carry a re-review.
    Absent (→ block) when no such typed APPROVE verdict exists."""
    from backend.forge.repos import activities as activities_repo
    reviewer = (ctx or {}).get("reviewer")
    since = (ctx or {}).get("since")
    if not reviewer or since is None:
        return Evidence.absent("human_approval",
                               "no reviewer/run context to bind the verdict")
    verdict = activities_repo.latest_review_verdict(
        db, task_id=task.id, actor=reviewer, since=since)
    if verdict is None:
        return Evidence.absent(
            "human_approval",
            "no structured reviewer verdict recorded since the review started",
            source="review_verdict")
    if verdict != "approve":
        return Evidence.absent(
            "human_approval",
            f"reviewer verdict is '{verdict}', not an approval",
            source="review_verdict")
    return Evidence.of("human_approval", {"verdict": "approve", "reviewer": reviewer},
                       source="review_verdict")


def _register_defaults() -> None:
    register(Provider("github_pr", ttl_seconds=60,
                      schema={"merged": "bool", "review_decision": "str",
                              "url": "str"},
                      fetch=_fetch_github_pr))
    register(Provider("ci", ttl_seconds=60,
                      schema={"checks": "dict[name -> {conclusion}]"},
                      fetch=_fetch_ci))
    register(Provider("commit", ttl_seconds=300,
                      schema={"sha": "str", "verified": "bool"},
                      fetch=_fetch_commit))
    register(Provider("human_approval", ttl_seconds=0,
                      schema={"verdict": "str", "reviewer": "str"},
                      fetch=_fetch_human_approval))


_register_defaults()
