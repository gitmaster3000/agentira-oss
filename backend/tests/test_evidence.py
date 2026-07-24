"""WFE Phase 2: evidence provider registry."""

import json

from backend.forge import evidence


def test_default_providers_registered():
    assert set(evidence.namespaces()) == {
        "github_pr", "ci", "commit", "human_approval"}
    for ns in evidence.namespaces():
        prov = evidence.get(ns)
        assert prov.namespace == ns
        assert isinstance(prov.schema, dict) and prov.schema
        assert prov.ttl_seconds >= 0


def test_absent_is_the_typed_default_and_blocks():
    """A provider that can't establish its fact returns absent, never a bare
    truthy value — absent is what a terminal gate blocks on."""
    ev = evidence.Evidence.absent("ci", "no creds")
    assert ev.present is False
    assert ev.reason == "no creds"
    # Snapshot is JSON-serializable for the gate_evaluations row.
    assert json.loads(json.dumps(ev.to_dict()))["present"] is False


def test_provider_exception_becomes_absent_not_raise():
    """A flaky provider must NOT crash the driver, and must NOT be read as
    approval — it degrades to typed-absent (block)."""
    def boom(task, db, ctx):
        raise RuntimeError("api down")
    evidence.register(evidence.Provider("flaky", ttl_seconds=0, schema={"x": "bool"},
                                        fetch=boom))
    try:
        ev = evidence.evaluate("flaky", task=_FakeTask(), db=None)
        assert ev.present is False
        assert "api down" in ev.reason
    finally:
        evidence._REGISTRY.pop("flaky", None)


def test_remote_providers_absent_without_platform_app():
    """github_pr / ci / commit read remote git state via the org GitHub App.
    With no App configured they are absent (block) — they never fall back to
    an agent token or assume the fact is true."""
    for ns in ("github_pr", "ci", "commit"):
        ev = evidence.evaluate(ns, task=_FakeTask(), db=None)
        assert ev.present is False
        assert "not configured" in ev.reason


def test_named_check_convention():
    ev = evidence.Evidence.of(
        "ci", {"checks": {"build": {"conclusion": "success"},
                          "lint": {"conclusion": "failure"}}}, source="gh")
    assert ev.check("build") == {"conclusion": "success"}
    assert ev.passed("build") is True
    assert ev.passed("lint") is False
    assert ev.check("missing") is None
    assert ev.passed("missing") is False
    # An absent evidence yields no checks.
    assert evidence.Evidence.absent("ci", "x").check("build") is None


class _FakeTask:
    id = "task_fake"
