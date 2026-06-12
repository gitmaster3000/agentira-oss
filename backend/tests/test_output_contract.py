"""The task output contract is config (templates/workflow/prompts/
output_contract.md), not an inline Python string — and it must demand the
full evidence chain: commit → push → verify → DoD → artifact. The SP-12
failure (agent claimed a commit hash that never existed, never pushed) is
the class this contract closes at the prompt layer; AP-81's server-side
verification is the enforcement layer above it.
"""

from __future__ import annotations

import json

from backend.forge.services import _build_task_prompt


class _T:
    title = "Build feature"
    description = "Do the thing."
    dod_items = json.dumps([{"text": "done it", "checked": False}])


def test_prompt_includes_contract_from_template():
    p = _build_task_prompt(_T())
    assert "## Output contract" in p
    assert '"{run_id}"' in p                      # caller substitutes run id
    assert "## Definition of Done" in p


def test_contract_demands_push_and_verification():
    p = _build_task_prompt(_T())
    assert "git push -u origin" in p              # push, not just commit
    assert "git cat-file -t" in p                 # hash must be verified
    assert "git ls-remote origin" in p            # push must be verified


def test_repo_check_block_is_config_too():
    p = _build_task_prompt(_T())
    assert "## Before you start — check you're in the right repo" in p
