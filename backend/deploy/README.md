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
- `railway.py` (AP-318) — `RailwayAdapter`, the first real adapter. Talks to
  Railway's Public GraphQL API through the `RailwayApi` seam (the only place
  that touches the network; tests replace it with a fake). *Not* the `railway`
  CLI — the backend runs as a container image with no CLI binary and no local
  working dir to `railway up`; the API deploys a commit of the service's
  connected repo instead. Compose services map 1:1 to Railway services (names
  resolved to ids via `project(id)`); `test`/`prod` select the Railway
  environment; the token comes from `RAILWAY_TOKEN` in the process env.
  Registered for `TargetKind.RAILWAY` on `import backend.deploy`.
- `docker.py` — `DockerAdapter` for `TargetKind.DOCKER`: local Docker on the
  user's own computer. Runs on the **daemon**, not here (see below).
- `dry_run.py` — `DryRunAdapter`, an in-memory reference adapter used to
  validate the contract.
- `conformance.py` — `run_conformance_suite(adapter, target)`: deploy ->
  status transitions -> teardown. AP-317/AP-318 run their real adapters
  through this too.

## Verifying a Railway key (AP-446)

Three things about Railway's API bite, and all three showed up as the same
useless symptom — *"your key is invalid"* for a key that was perfectly good:

1. **Cloudflare fronts the API and 403s the stdlib's default User-Agent**
   (`Python-urllib/3.x`) with `error code: 1010`. The request never reaches
   Railway. `RailwayApi` therefore sends its own `User-Agent` on every call —
   do not remove it. `curl` works fine, which is exactly why this survived
   manual testing.
2. **`me` is a personal-token-only query.** A workspace/team key authenticates
   fine but has no user behind it, so Railway answers `Not Authorized`.
   Verification probes `me` first and falls back to `projects`, which every
   token type can run.
3. **"We couldn't check" is not "your key is bad."** `verify_credential`
   returns `None` (not `False`) when Railway was unreachable or an edge blocked
   us, and the UI must say so rather than blaming the user's key. That is what
   `AuthError` vs `TransportError`/`BlockedError` exist to separate.

A mocked test cannot catch (1) — the transport is the thing that's broken. The
regression gate is `bruno/rest/11-deploy`, which probes a **real** key against
the **real** API. Run it against pre-prod before touching this code.

## Secrets-from-env (ADR-011 §3)

Deploy credentials (Railway token, GCP service account key, kubeconfig,
GitHub Deployments token) are **environment variables the daemon supplies
to the deploy adapter process** — never:

- committed to the repo,
- present in the agent's own task container/filesystem,
- returned through an MCP tool result, task comment, or activity log
  (redact to `"configured: yes/no"` if a caller needs to check presence).

The `docker` adapter needs no external credential (`requires_credential =
False`) — the daemon shells out to its host's local Docker/compose CLI. `github_deployments.py`
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

## Local Docker (`docker.py` + `agentira-cli/agentira_cli/daemon/deploy.py`)

The backend container can't reach the host's Docker, so the docker adapter
never runs `docker`. It mirrors workflow integration:

1. `DockerAdapter.prepare()` resolves the computer (`runtime_id`: config, else
   any online daemon runtime in the org) and the repo (`source_url`: config,
   else the project's primary repo).
2. `deploy()` validates the branch/ref (no leading `-`, no `..`, no shell
   metacharacters), sends a `deploy` WS frame via `hub.dispatch_deploy`
   (durable through the dispatch outbox), and returns `pending` with handle
   `<runtime_id>:<key>`, `key = agentira-<branch-slug>-<sha(project,branch)>`.
3. The daemon clones the ref into `~/.agentira/deploys/<project>/<branch>/src`
   (daemon-owned, never an agent worktree), then `docker compose up -d
   --build` when the repo has a compose file, else `docker build` + `docker
   run`. The public port is derived from `key` (20000–29999, next free on
   collision, kept across redeploys) and bound to `127.0.0.1`. Compose ports
   are remapped through a generated override file (the public service gets
   the port, other services' published ports are dropped), so branches never
   collide. Everything is labelled `agentira.deploy=<key>` (+ project, branch).
4. The daemon health-probes `health_path` (default `/`) and POSTs progress,
   logs and the final status/URL to `/api/forge/daemon/deploy-result`;
   `DeployFlow.apply_daemon_result` writes them onto the deployment row.
5. `teardown` / `status` / `logs` are the same frame with a different
   `action`. Teardown runs `docker compose down -v --rmi local`, removes any
   container/network/volume still carrying the label, and deletes the checkout.

Target config (all optional): `source_url`, `runtime_id`, `health_path`,
`service` (public compose service), `container_port`.

Tests: `backend/tests/test_deploy_docker.py` (daemon seam faked) and
`agentira-cli/tests/test_deploy_docker.py` (real Docker: single-container and
2-service compose fixtures; skipped when Docker is unavailable). A compose file
that pins `container_name` can't run two branches side by side — that's the
app's constraint, not ours.
