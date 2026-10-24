"""Deterministic text for the sample dataset (AP-699). Pure functions of an rng."""
from __future__ import annotations

import random

_NOUNS = ["board", "sprint", "agent", "pipeline", "dashboard", "report", "webhook", "invoice",
          "cache", "query", "migration", "notification", "permission", "timeline", "export",
          "importer", "scheduler", "audit log", "settings page", "search index", "worker"]
_VERBS = ["refactor", "validate", "paginate", "debounce", "backfill", "index", "memoize",
          "retry", "summarise", "normalise", "stream", "archive", "reconcile", "throttle"]
_ADJ = ["slow", "flaky", "legacy", "noisy", "duplicated", "unbounded", "stale", "inconsistent",
        "fragile", "undocumented", "expensive", "confusing"]
_VERB_PHRASES = ["Fix", "Add", "Improve", "Speed up", "Document", "Replace", "Split", "Harden",
                 "Simplify", "Audit", "Migrate", "Instrument"]
TAGS = ["frontend", "backend", "ux", "perf", "infra", "docs", "bug", "tech-debt", "api", "data",
        "security", "mobile", "reporting", "onboarding"]
COMMENTS = [
    "Looked into this — the {a} {n} is the cause, not the {n2}.",
    "Pushed a first pass, can you take a look @{who}?",
    "Blocked on the {n}; will pick up once it lands.",
    "Confirmed on staging. Repro steps in the description.",
    "Nice. Can we also {v} the {n} while we are here?",
    "@{who} thoughts on splitting this into two tasks?",
    "Measured before/after: the {n} went from 840 ms to 120 ms.",
    "Reviewed — two small nits, otherwise good to go.",
    "Moving to review, all checks green.",
]


def title(rng: random.Random) -> str:
    return f"{rng.choice(_VERB_PHRASES)} {rng.choice(_ADJ)} {rng.choice(_NOUNS)} {rng.choice(['flow', 'handling', 'logic', 'view', 'path'])}"


def sentence(rng: random.Random) -> str:
    return (f"The {rng.choice(_ADJ)} {rng.choice(_NOUNS)} should {rng.choice(_VERBS)} "
            f"every {rng.choice(_NOUNS)} before the {rng.choice(_NOUNS)} runs, so reviewers "
            f"see the same result on every {rng.choice(_NOUNS)}.")


def paragraph(rng: random.Random, n: int | None = None) -> str:
    return " ".join(sentence(rng) for _ in range(n or rng.randint(2, 5)))


def comment(rng: random.Random, who: str) -> str:
    return rng.choice(COMMENTS).format(
        a=rng.choice(_ADJ), n=rng.choice(_NOUNS), n2=rng.choice(_NOUNS),
        v=rng.choice(_VERBS), who=who)


def _bullets(rng: random.Random) -> str:
    return "\n".join(f"- {sentence(rng)}" for _ in range(rng.randint(3, 7)))


def _table(rng: random.Random) -> str:
    rows = "\n".join(
        f"| {rng.choice(_NOUNS)} | {rng.randint(20, 900)} ms | {rng.choice(['ok', 'slow', 'flaky'])} |"
        for _ in range(rng.randint(4, 9)))
    return f"| Area | Latency | Status |\n|---|---|---|\n{rows}"


def _code(rng: random.Random) -> str:
    fn = rng.choice(_VERBS)
    body = "\n".join(f"    result.append(item.{rng.choice(_VERBS)}())" for _ in range(rng.randint(3, 9)))
    return f"```python\ndef {fn}_all(items):\n    result = []\n    for item in items:\n{body}\n    return result\n```"


def _quote(rng: random.Random) -> str:
    return f"> {paragraph(rng, 2)}"


def _checklist(rng: random.Random) -> str:
    return "\n".join(f"- [{rng.choice([' ', 'x'])}] {title(rng)}" for _ in range(rng.randint(3, 6)))


_SECTIONS = [("Context", paragraph), ("Requirements", _bullets), ("Measurements", _table),
             ("Proposed change", _code), ("Notes", _quote), ("Open questions", _bullets),
             ("Plan", _checklist), ("Rollout", paragraph), ("Risks", _bullets),
             ("Background", paragraph), ("Acceptance", _checklist)]


def long_markdown(rng: random.Random, name: str, target: int) -> str:
    """Markdown with headings, tables, code and lists, `target`..8000 chars."""
    out = f"# {name}\n\n{paragraph(rng)}\n"
    i = 0
    while len(out) < target:
        head, fn = _SECTIONS[i % len(_SECTIONS)]
        chunk = f"\n## {head}\n\n{fn(rng)}\n"
        if len(out) + len(chunk) > 8000:
            break
        out += chunk
        i += 1
    return out


def dod_items(rng: random.Random, done: bool) -> list[dict]:
    items = ["Tests added and passing", "Docs updated", "Reviewed by a second person",
             "Works on mobile width", "No new network calls on page load", "Proof attached"]
    n = rng.randint(2, 5)
    return [{"text": t, "checked": done or rng.random() < 0.4} for t in items[:n]]
