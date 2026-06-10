"""AP-202: workspace_kind is resolved and threaded into the dispatch frame.

The daemon used to guess git-vs-sandbox from URL presence, which left sandbox
runs with a phantom worktree_branch. Now the backend resolves the kind
(explicit column wins, else inferred) and threads it; sandbox blanks the
worktree fields.
"""

from __future__ import annotations

import inspect

from backend.forge.services import _resolve_workspace_kind, dispatch_trigger


class _Proj:
    def __init__(self, workspace_kind=None, repo_url=None, repo_path=None):
        self.workspace_kind = workspace_kind
        self.repo_url = repo_url
        self.repo_path = repo_path


def test_explicit_kind_wins():
    assert _resolve_workspace_kind(_Proj(workspace_kind="git")) == "git"
    assert _resolve_workspace_kind(_Proj(workspace_kind="sandbox")) == "sandbox"
    assert _resolve_workspace_kind(_Proj(workspace_kind="local_folder")) == "local_folder"


def test_explicit_kind_overrides_inference():
    # column says sandbox even though a url is present
    assert _resolve_workspace_kind(_Proj(workspace_kind="sandbox", repo_url="x")) == "sandbox"


def test_inference_when_column_blank():
    assert _resolve_workspace_kind(_Proj(repo_url="https://x/y.git")) == "git"
    assert _resolve_workspace_kind(_Proj(repo_path="/x")) == "local_folder"
    assert _resolve_workspace_kind(_Proj()) == "sandbox"


def test_none_project_is_sandbox():
    assert _resolve_workspace_kind(None) == "sandbox"


def test_unknown_kind_string_falls_back_to_inference():
    assert _resolve_workspace_kind(_Proj(workspace_kind="bogus", repo_url="x")) == "git"
    assert _resolve_workspace_kind(_Proj(workspace_kind="")) == "sandbox"


def test_dispatch_trigger_accepts_workspace_kind():
    assert "workspace_kind" in inspect.signature(dispatch_trigger).parameters
