# Daemon / CLI Release Runbook (maintainers)

How to ship a change to `agentira-cli` (the daemon) so it reaches running
installs. This is the **publish** side; for diagnosing/restarting a live
daemon see [`daemon_runbook.md`](daemon_runbook.md).

> **The one-line rule:** a code change to `agentira-cli/` does **not** reach any
> daemon until you (1) bump the version, (2) rebuild + rebake the wheel, and
> (3) redeploy the backend. Merging to `main` alone changes nothing on a
> customer's machine.

## How a change reaches a daemon

```
edit agentira-cli/  →  bump version in pyproject.toml  →  merge + deploy backend
      →  backend Docker build rebuilds the wheel + manifest from source
      →  GET /api/public/cli-release now reports the new version
      →  customer runs `agentira daemon update` (pip installs the wheel)
      →  customer runs `agentira daemon restart` (loads new code)
```

The wheel is **built inside the backend Docker image**, not committed
(`backend/static/cli/wheels/*.whl` and `manifest.json` are gitignored). See
`Dockerfile` — every Railway deploy runs `python -m build agentira-cli/` then
`scripts/write_cli_manifest.py`. **You only commit the version bump.**

Two independent things must both happen or the fix silently no-ops:

| If you skip…            | Symptom                                                        |
|-------------------------|---------------------------------------------------------------|
| the **version bump**    | `daemon update` says "Already on the latest release" forever — the wheel changed but the version didn't, so the daemon never reinstalls. |
| the **daemon restart**  | `update` installs new code, but the running process still executes the old code in memory. |

## Versioning

- **Scheme:** semver `MAJOR.MINOR.PATCH`.
- **Single source of truth:** `agentira-cli/pyproject.toml` → `version`.
  `agentira_cli/_version.py` reads it from installed package metadata at
  runtime — never hard-code a version anywhere else.
- **When to bump:** any change under `agentira-cli/agentira_cli/` that you want
  a running daemon to pick up. Bug fix / behavior tweak → PATCH. New
  daemon capability → MINOR. Wire-protocol break with the backend → MAJOR.

## Release steps

The wheel is generated on deploy, so a release is just a **version bump + a
backend redeploy**.

```bash
# 1. Bump the version (single source of truth)
#    edit agentira-cli/pyproject.toml:  version = "0.1.3"

# 2. Commit just the bump (+ your code change + any docs)
git add agentira-cli/pyproject.toml
git commit -m "release(cli): daemon 0.1.3 — <one-line what changed>"

# 3. (Optional) tag to run the wheel-build CI check before deploying
git tag agentira-cli-v0.1.3 && git push origin agentira-cli-v0.1.3
#    → .github/workflows/release-agentira-cli.yml verifies the wheel builds
#      cleanly (it does NOT publish — the backend deploy does that)

# 4. Merge to main. Railway auto-deploys the backend on merge — no manual
#    deploy step. The Dockerfile runs `python -m build agentira-cli/` +
#    write_cli_manifest.py, baking the fresh wheel + manifest into the image,
#    and GET /api/public/cli-release then serves the new version.
```

To **test locally** before deploying (build the wheel + manifest into the
gitignored static dir the way the Docker build does):

```bash
python -m build --wheel --outdir backend/static/cli/wheels/ agentira-cli
rm -f backend/static/cli/wheels/agentira_cli-<OLD>-py3-none-any.whl
python scripts/write_cli_manifest.py     # writes backend/static/cli/manifest.json
```

These files are gitignored — do **not** commit them.

### What the backend serves

`backend/cli_release.py` reads `backend/static/cli/manifest.json` and returns:

```json
{
  "version": "0.1.3",
  "min_python": "3.11",
  "install_url": "https://<instance>/api/public/cli/wheels/agentira_cli-0.1.3-py3-none-any.whl",
  "install_sh_url": "...", "install_ps1_url": "..."
}
```

The daemon's `update_check.py` fetches this, compares `version` against the
installed one, and `pip install`s `install_url` if newer.

## Verify a release

```bash
# Backend is serving the new version:
curl -s https://<instance>/api/public/cli-release | python3 -m json.tool
#   → "version": "0.1.3"

# A daemon picks it up:
agentira daemon update            # → "Update available: 0.1.2 → 0.1.3"
agentira daemon update -y --restart
agentira daemon status            # → CLI: agentira-cli 0.1.3, WS connected
```

Then exercise the actual code path you changed (e.g. run a chat/agent) — a
version number is not proof the fix works.

## Rollback

Re-release the previous version as a *higher* number (e.g. revert the code,
bump `0.1.3 → 0.1.4`), rebuild, redeploy. `daemon update` only ever moves
**forward** (`is_newer` compares tuples), so you cannot ship "0.1.2" again to
downgrade — cut a new patch that contains the old code.

## Gotchas learned the hard way

- **Editable installs pin the version at install time.** `pip install -e`
  records whatever `pyproject.toml` said *when you ran it*. Bump the version
  *before* installing, or reinstall (`pip install -e .`) after bumping, or
  `agentira --version` lies.
- **`daemon update` can't pull a same-version wheel.** If you rebuild the wheel
  without bumping, the endpoint reports the same version and every daemon skips
  it. Always bump.
- **The gateway connect frame is an enum contract.** `client.id` /
  `client.mode` in `runtimes/gateway_connect.py` must be members of OpenClaw's
  `GATEWAY_CLIENT_IDS` / `GATEWAY_CLIENT_MODES`, and the offered protocol range
  must straddle what the installed gateway speaks. `test_gateway_connect_contract.py`
  fails CI if they drift — do not "fix" it by inventing values; align with the
  installed OpenClaw enums (see PR #220 for the incident this came from).
- **A wheel only ships the code committed at build time.** Build from a clean
  checkout of the version you're tagging, not a dirty tree.
