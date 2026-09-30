"""GitHub pull-request seam for branch integration.

The daemon asks GitHub two things: "what state is this PR in?" and "merge it".
Both go through the `gh` CLI, i.e. the user's own GitHub login — the same
ambient credentials `git` already uses on this machine. Tests swap in a fake
with the same two methods.
"""

from __future__ import annotations

import json
import re
import subprocess

_TIMEOUT = 60
_SLUG_RE = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
_HTTP_RE = re.compile(r"HTTP (\d{3})")


class GitHubError(Exception):
    """GitHub could not be reached or asked (gh missing, not logged in, …)."""


def repo_slug(source_url: str) -> str:
    """`owner/repo` from a GitHub remote URL (https, ssh or scp style)."""
    m = _SLUG_RE.search((source_url or "").strip())
    if not m:
        raise GitHubError(f"not a GitHub repository: {source_url or '(no url)'}")
    return f"{m.group(1)}/{m.group(2)}"


def _gh(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              timeout=_TIMEOUT)
    except FileNotFoundError:
        raise GitHubError("the gh command is not installed on this machine")
    except subprocess.TimeoutExpired:
        raise GitHubError("GitHub did not answer in time")


class GhCli:
    def pr_status(self, source_url: str, number: int) -> dict:
        r = _gh("api", f"repos/{repo_slug(source_url)}/pulls/{number}")
        if r.returncode != 0:
            raise GitHubError((r.stderr or r.stdout).strip()[:300])
        pr = json.loads(r.stdout)
        return {"state": pr.get("state", ""), "merged": bool(pr.get("merged")),
                "mergeable": pr.get("mergeable"),
                "mergeable_state": pr.get("mergeable_state", ""),
                "base_ref": (pr.get("base") or {}).get("ref", ""),
                "head_sha": (pr.get("head") or {}).get("sha", "")}

    def merge_pr(self, source_url: str, number: int, *, method: str,
                 sha: str) -> tuple[bool, str, str]:
        """(ok, failure_kind, message). `sha` pins the head GitHub may merge,
        so code that changed after it was checked is never merged."""
        r = _gh("api", "-X", "PUT",
                f"repos/{repo_slug(source_url)}/pulls/{number}/merge",
                "-f", f"merge_method={method}", "-f", f"sha={sha}")
        if r.returncode == 0:
            return True, "", "merged"
        text = ((r.stdout or "") + (r.stderr or "")).strip()
        try:
            message = json.loads(text.splitlines()[0]).get("message", "")
        except (ValueError, IndexError, AttributeError):
            message = ""
        message = (message or text)[:300]
        m = _HTTP_RE.search(text)
        status = int(m.group(1)) if m else 0
        return False, ("pr_head_moved" if status == 409 else "pr_not_mergeable"), message
