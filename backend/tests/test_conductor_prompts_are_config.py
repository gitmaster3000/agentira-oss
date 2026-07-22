"""Prompts-are-config regression guard for the Conductor.

Hard rule: no LLM prompt prose may be inlined in conductor.py — the agent
system prompt and the per-turn planning/report templates all live as
Markdown under templates/conductor/. Code only loads the file and fills
in the dynamic facts. These tests fail if prose creeps back into code or a
template loses its variable placeholders.
"""

from __future__ import annotations

from pathlib import Path

from backend.forge import conductor


_SRC = Path(conductor.__file__).read_text(encoding="utf-8")


def test_system_prompt_loads_from_file_not_code():
    sp = conductor._conductor_system_prompt()
    assert sp.startswith("You are the Conductor")
    # The prose must NOT be present as a triple-quoted literal in the module.
    assert "keep task queues moving and runs healthy" not in _SRC


def test_planning_prompt_is_template_driven():
    facts = {
        "project_id": "P1", "project_name": "Project One",
        "agents": [{"name": "implementer-1", "project_id": "P1",
                    "in_flight": 0, "capacity": 1}],
        "unassigned_tasks": [{"id": "t1", "key": "AP-9", "title": "Do thing",
                              "project_id": "P1", "priority": "high"}],
        "backlog": [{"id": "t2", "key": "AP-10", "title": "Promote me",
                    "project_id": "P1", "priority": "medium"}],
        "capacity": 1,
    }
    out = conductor._compose_planning_prompt(facts)
    assert "QUEUE PLANNING" in out
    assert "implementer-1" in out and "AP-9" in out and "AP-10" in out
    assert "Project One" in out
    assert "{{" not in out and "}}" not in out  # every placeholder filled
    # Instruction prose lives in the template, not the module.
    assert "best-fit agent IN THE SAME" not in _SRC
    # Section C: the injection guard is prepended to every composed turn.
    assert "untrusted" in out.lower() or "DATA" in out


def test_report_prompt_is_template_driven():
    facts = {
        "projects": [{"project": "P1",
                      "counts": {"done": 2, "blocked": 1, "needs_input": 0,
                                 "failed": 0, "in_flight": 1},
                      "stats": {"cost_usd": 0.12}}],
        "survey": {"agents": [{"name": "implementer-1", "in_flight": 1,
                               "capacity": 1, "next_task": None}]},
    }
    out = conductor._compose_report_prompt(facts)
    assert "DAILY REPORT" in out and "daily-report" in out
    assert "{{" not in out and "}}" not in out
    assert "self-contained HTML fragment" not in _SRC
