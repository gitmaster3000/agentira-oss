"""AP-302: git access tokens (PATs) for project repos and agents.

A token lets a dispatched agent clone/push private repos. Tokens live on
`ProjectRepo.access_token` (per repo) and `Profile.git_token` (per agent,
used as a fallback). This module only knows how to *verify* a token against
GitHub — storage + REST wiring live in services/rest_api.

Verification is a single GitHub API call (stdlib urllib, no new dep):
  - if a github.com repo URL is known, probe GET /repos/{owner}/{repo}
    (confirms the token can actually see THAT repo);
  - otherwise probe GET /user (confirms the token authenticates at all).

ponytail: GitHub-only. GitLab/Bitbucket/self-hosted would key off the host
in repo_url and hit their own /user endpoint — add when a non-GitHub remote
shows up.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

_GITHUB_REPO_RE = re.compile(
    r"github\.com[:/]+([^/]+)/(.+?)(?:\.git)?/?$"
)


def parse_github_repo(repo_url: str | None) -> tuple[str, str] | None:
    """Return (owner, repo) for a github.com URL, else None."""
    if not repo_url:
        return None
    m = _GITHUB_REPO_RE.search(repo_url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def verify_git_token(token: str, repo_url: str | None = None,
                     timeout: float = 8.0) -> tuple[bool, str]:
    """Probe a git token against GitHub. Returns (valid, detail).

    `detail` is a short human-readable reason (shown in the UI tooltip).
    Network/unexpected errors return (False, reason) — we never raise so a
    flaky probe just reads as "invalid, retry".
    """
    token = (token or "").strip()
    if not token:
        return False, "no token"

    owner_repo = parse_github_repo(repo_url)
    if owner_repo:
        url = f"https://api.github.com/repos/{owner_repo[0]}/{owner_repo[1]}"
        ok_detail = "token can access the repo"
    else:
        url = "https://api.github.com/user"
        ok_detail = "token authenticates"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentira",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (200 <= resp.status < 300), ok_detail
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "token rejected (401/403)"
        if e.code == 404:
            return False, "repo not found or token can't see it (404)"
        return False, f"github returned {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"could not reach github: {e}"


def _gh_request(path: str, token: str | None, timeout: float):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentira",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(f"https://api.github.com{path}", headers=headers)


def repo_access(repo_url: str | None, token: str | None,
                timeout: float = 8.0) -> tuple[bool, str]:
    """Does `token` actually let us build this GitHub repo? Returns
    (granted, plain_reason). Plain-language reason for the UI — never a stack
    trace. A non-GitHub / unparsable repo is (False, reason), never a crash."""
    parsed = parse_github_repo(repo_url)
    if not parsed:
        return False, "No GitHub repository is linked to this project yet."
    if not token:
        return False, "No access token on file — connect one so we can reach the repository."
    owner, repo = parsed
    try:
        with urllib.request.urlopen(
                _gh_request(f"/repos/{owner}/{repo}", token, timeout),
                timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True, f"Connected to {owner}/{repo}."
            return False, f"GitHub returned {resp.status} for {owner}/{repo}."
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, "The access token was rejected — check it hasn't expired or lost access."
        if e.code == 404:
            return False, f"Can't see {owner}/{repo} — the token may not have access to it."
        return False, f"GitHub returned an error ({e.code}) checking access."
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, "Couldn't reach GitHub to check access — try again in a moment."


def list_repo_branches(repo_url: str | None, token: str | None,
                       timeout: float = 8.0) -> list[str]:
    """Real branch names for a GitHub repo (first page, up to 100). Returns
    [] when the repo is unlinked/unreachable — callers fall back gracefully."""
    parsed = parse_github_repo(repo_url)
    if not parsed:
        return []
    owner, repo = parsed
    try:
        with urllib.request.urlopen(
                _gh_request(f"/repos/{owner}/{repo}/branches?per_page=100",
                            token, timeout),
                timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    return [b["name"] for b in data if isinstance(b, dict) and b.get("name")]


if __name__ == "__main__":
    # ponytail self-check: URL parsing is the only non-trivial logic here
    # (the HTTP call needs the network). Run: python -m backend.repo_tokens
    assert parse_github_repo("https://github.com/acme/widgets.git") == ("acme", "widgets")
    assert parse_github_repo("https://github.com/acme/widgets") == ("acme", "widgets")
    assert parse_github_repo("git@github.com:acme/widgets.git") == ("acme", "widgets")
    assert parse_github_repo("https://gitlab.com/acme/widgets.git") is None
    assert parse_github_repo("") is None
    assert parse_github_repo(None) is None
    assert verify_git_token("", None) == (False, "no token")
    print("ok")
