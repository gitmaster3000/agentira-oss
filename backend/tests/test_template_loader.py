"""AP-3: load_template(path) — pure YAML → Template parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.template_loader import load_template, Template


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_BUNDLED = _REPO_ROOT / "templates" / "production-readiness.yaml"


def test_loads_bundled_production_readiness_template():
    t = load_template(_BUNDLED)
    assert isinstance(t, Template)
    assert t.name == "Production Readiness"
    assert len(t.columns) == 7
    assert len(t.agents) == 6
    assert len(t.ac_check_types) == 6
    # Conductor block parsed with defaults filled in.
    assert t.conductor.auto_assign is True
    # First agent shape.
    assert t.agents[0].name == "Auditor"
    assert t.agents[0].role == "auditor"
    assert "get_task" in t.agents[0].allowed_tools


def test_missing_file_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        load_template("/nonexistent/path/template.yaml")


def test_malformed_yaml_raises_valueerror(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed\n")
    with pytest.raises(ValueError):
        load_template(bad)


def test_non_mapping_top_level_raises_valueerror(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError):
        load_template(bad)


def test_empty_name_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("name: '  '\ncolumns: [A]\nagents:\n  - {name: X, role: r, model: m}\n")
    with pytest.raises(ValueError):
        load_template(f)


def test_no_columns_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("name: T\ncolumns: []\nagents:\n  - {name: X, role: r, model: m}\n")
    with pytest.raises(ValueError):
        load_template(f)


def test_no_agents_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text("name: T\ncolumns: [A]\nagents: []\n")
    with pytest.raises(ValueError):
        load_template(f)


def test_minimal_valid_template(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: Minimal\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
    )
    t = load_template(f)
    assert t.name == "Minimal"
    assert t.version == "1.0.0"  # default
    assert t.agents[0].allowed_tools == []  # default
    assert t.default_tasks == []  # default
    assert t.workflow_columns == []  # default
    assert t.workflow_roles == {}  # default


def test_default_tasks_ref_resolved(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithDefaults\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "default_tasks:\n"
        "  - professionalization\n"
    )
    t = load_template(f)
    assert t.default_tasks == ["professionalization"]


def test_default_tasks_ref_missing_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithDefaults\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "default_tasks:\n"
        "  - does-not-exist\n"
    )
    with pytest.raises(ValueError):
        load_template(f)


def test_workflow_columns_must_be_subset_of_columns(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithWorkflow\n"
        "columns: [Todo, In Progress, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "workflow_columns: [Todo, Done]\n"
    )
    t = load_template(f)
    assert t.workflow_columns == ["Todo", "Done"]


def test_workflow_columns_unknown_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithWorkflow\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "workflow_columns: [Todo, Review]\n"
    )
    with pytest.raises(ValueError):
        load_template(f)


def test_workflow_roles_override_parsed(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithRoles\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "workflow_roles:\n"
        "  reviewer:\n"
        "    match: [review, senior]\n"
        "    exclude_previous_assignee: true\n"
        "    fallback: any\n"
    )
    t = load_template(f)
    assert "reviewer" in t.workflow_roles
    assert t.workflow_roles["reviewer"].match == ["review", "senior"]
    assert t.workflow_roles["reviewer"].exclude_previous_assignee is True
    assert t.workflow_roles["reviewer"].fallback == "any"


def test_workflow_roles_bad_fallback_rejected(tmp_path):
    f = tmp_path / "t.yaml"
    f.write_text(
        "name: WithRoles\n"
        "columns: [Todo, Done]\n"
        "agents:\n"
        "  - {name: Solo, role: implementer, model: claude-sonnet-4-5}\n"
        "workflow_roles:\n"
        "  reviewer:\n"
        "    fallback: sometimes\n"
    )
    with pytest.raises(ValueError):
        load_template(f)
