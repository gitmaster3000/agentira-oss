"""Regression: a malformed DoD item must never poison storage or crash reads.

Bug: create_task json.dumps'd dod_items verbatim, so a caller passing plain
strings persisted a list[str]. _dod_progress then did item.get("checked")
on a str -> AttributeError, which 500'd list_tasks for the ENTIRE project
(the board showed "project not found"). One bad row took down 190 tasks.

Fix: _normalize_dod coerces every item to {text, checked} on both write and
read (legacy rows self-heal), and _dod_progress is defensive.
"""

from __future__ import annotations

from backend.services import _normalize_dod, _dod_progress


def test_strings_coerce_to_unchecked_items():
    out = _normalize_dod(["do A", "do B"])
    assert out == [
        {"text": "do A", "checked": False},
        {"text": "do B", "checked": False},
    ]


def test_dicts_pass_through_canonically():
    out = _normalize_dod([
        {"text": "x", "checked": True},
        {"label": "y"},  # legacy 'label' key
    ])
    assert out == [
        {"text": "x", "checked": True},
        {"text": "y", "checked": False},
    ]


def test_mixed_and_junk_items_are_safe():
    out = _normalize_dod(["s", {"text": "d", "checked": True}, None, 7])
    assert out == [
        {"text": "s", "checked": False},
        {"text": "d", "checked": True},
    ]


def test_empty_is_none():
    assert _normalize_dod(None) is None
    assert _normalize_dod([]) is None


def test_dod_progress_never_crashes_on_legacy_strings():
    # Simulates a row stored before the fix: bare strings.
    assert _dod_progress(["a", "b"]) == {"total": 2, "checked": 0}
    # Mixed legacy + canonical.
    assert _dod_progress(["a", {"checked": True}]) == {"total": 2, "checked": 1}
