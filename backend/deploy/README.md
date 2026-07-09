# backend/deploy — deploy adapter contract (AP-316)

Foundation for the deployment epic (ADR-011). Defines the adapter contract
only — no real adapter ships here (AP-317 docker, AP-318 railway build on
this), no settings storage (AP-314), no `Task` columns (AP-315).

## Files

- `contract.py` — `Capability`, `TargetKind`, `Environment`,
  `DeploymentStatus`, `DeployTargetConfig` (Pydantic, validated config
  parsing), `DeploymentResult`.
- `adapter.py` — `DeployAdapter` ABC, mirrors `RuntimeAdapter`
  (`backend/forge/runtime_client.py:59`). `deploy/status/logs/preview_url/
  teardown`, capability-gated no-ops via `unsupported_result()` instead of
  exceptions for whatever a target kind can't do.
- `registry.py` — `register(kind, adapter)` / `get_adapter(kind)`, one
  instance per `TargetKind`.
- `github_deployments.py` — records to the GitHub Deployments API when a
  repo is linked; skips cleanly (returns `None`/`False`) otherwise.
- `dry_run.py` — `DryRunAdapter`, an in-memory reference adapter used to
  validate the contract.
- `conformance.py` — `run_conformance_suite(adapter, target)`: deploy ->
  status transitions -> teardown. AP-317/AP-318 run their real adapters
  through this too.

## Secrets-from-env (ADR-011 §3)

Deploy credentials (Railway token, GCP service account key, kubeconfig,
GitHub Deployments token) are **environment variables the daemon supplies
to the deploy adapter process** — never:

- committed to the repo,
- present in the agent's own task container/filesystem,
- returned through an MCP tool result, task comment, or activity log
  (redact to `"configured: yes/no"` if a caller needs to check presence).

The `docker` adapter (AP-317) needs no external credential — it shells out
to the daemon host's local Docker/compose CLI. `github_deployments.py`
takes its token as a plain function argument (`record_deployment(...,
token=...)`) rather than reading an env var itself, so the caller (a
future repo-layer/service module) is the one place that decides where the
token comes from — this module never reaches into `os.environ` on its
own.

`DeployTargetConfig.config` never carries a secret — it's adapter-specific
non-secret config (compose file path, Railway project/env id, GCP
project/region, ...). See ADR-011 §6.

`deploy.execute` autonomy gating (`auto|ask|deny`) is AP-320's job, not
this module's.
