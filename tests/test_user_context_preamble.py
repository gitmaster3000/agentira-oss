"""Tests for AP-76 user-context injection.

compose_system_prompt renders a synthetic preamble describing where
the user is (surface, project, route, nav history) BEFORE the
conventions pointer, memory addendum, and agent persona.
"""

import pytest

agentira_cli_mat = pytest.importorskip(
    "agentira_cli.daemon.materializer",
    reason="agentira-cli package not installed",
)
compose_system_prompt = agentira_cli_mat.compose_system_prompt
CONVENTIONS_ADDENDUM = agentira_cli_mat.CONVENTIONS_ADDENDUM


def test_no_user_context_omits_preamble():
    """Empty / None / missing user_context leaves the prompt clean."""
    for ctx in (None, {}, {"surface": ""}, {"nav_history": []}):
        out = compose_system_prompt("persona", have_conventions=False, user_context=ctx)
        assert "currently viewing" not in out
        assert out == "persona"


def test_user_context_renders_surface_and_project():
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={
            "surface": "forge_agent_chat",
            "project_name": "Agentira Platform",
            "route": "/forge/agents/abc",
        },
    )
    assert "forge_agent_chat" in out
    assert "Agentira Platform" in out
    assert "/forge/agents/abc" in out
    assert "When the user says" in out  # the disambiguation hint


def test_user_context_renders_nav_history():
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={
            "surface": "concierge",
            "nav_history": ["/a", "/b", "/c"],
        },
    )
    assert "Recent pages" in out
    assert "/a" in out and "/b" in out and "/c" in out


def test_nav_history_truncates_to_five():
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={
            "surface": "x",
            "nav_history": [f"/p{i}" for i in range(10)],
        },
    )
    # First 5 should be present, /p5 and beyond should not.
    for i in range(5):
        assert f"/p{i}" in out
    assert "/p5" not in out
    assert "/p9" not in out


def test_preamble_comes_before_conventions_and_persona():
    """Order matters — the preamble disambiguates 'this project' so
    later instructions can resolve it correctly."""
    out = compose_system_prompt(
        "Be careful.",
        have_conventions=True,
        user_context={"surface": "x", "project_name": "P", "route": "/y"},
    )
    pre_idx = out.index("currently viewing")
    conv_idx = out.index(CONVENTIONS_ADDENDUM)
    persona_idx = out.index("Be careful.")
    assert pre_idx < conv_idx < persona_idx


def test_falls_back_to_project_id_when_no_name():
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={"surface": "x", "project_id": "abc123"},
    )
    assert "abc123" in out


def test_task_context_renders():
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={
            "surface": "studio_task",
            "task_title": "Fix the thing",
            "task_id": "AP-99",
        },
    )
    assert "Fix the thing" in out
    # task_title wins; task_id only shows when title is empty
    assert "AP-99" not in out


def test_malformed_user_context_is_safe():
    """Non-dict user_context shouldn't crash anything."""
    out = compose_system_prompt("persona", have_conventions=False, user_context="not a dict")
    assert out == "persona"


def test_user_context_with_only_route_renders_minimally():
    """Just a route, nothing else — should still produce a useful preamble."""
    out = compose_system_prompt(
        "persona",
        have_conventions=False,
        user_context={"route": "/forge/agents/abc"},
    )
    assert "/forge/agents/abc" in out
    assert "When the user says" in out
