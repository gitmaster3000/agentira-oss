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
