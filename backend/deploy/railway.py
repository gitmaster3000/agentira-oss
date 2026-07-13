"""AP-318: `RailwayAdapter` — the first real deploy adapter (ADR-011 §2).

Talks to Railway's **Public GraphQL API** (`backboard.railway.com/graphql/v2`),
not the `railway` CLI: the backend runs as a container image on Railway, where
no CLI binary exists and there's no local working directory to `railway up`.
The API deploys a *ref* of the service's connected repo, which is exactly what
a deploy of a task's branch means here. Stdlib urllib only, same shape as
`backend/repo_tokens.py` / `github_deployments.py`.

Operations used (Railway Public API):

    me                                   verify a token
    serviceInstanceDeployV2              deploy a commit/branch to an env
    deployment(id)                       status, url/staticUrl
    buildLogs / deploymentLogs           logs
    deploymentRemove(id)                 teardown
    project(id)                          resolve service/environment names -> ids

Config (`DeployTargetConfig.config`, never a secret — ADR-011 §3/§6):

    project_id    Railway project id (required)
    services      compose service names, mapped 1:1 to Railway services
                  (devops convention). First = primary; its URL is the
                  deployment's URL. `service` (singular) also accepted.
                  Names are resolved to Railway service ids via `project(id)`.
    environments  {"test": "staging", "prod": "production"} — overrides the
                  default of using the `Environment` value as the Railway
                  environment name.

Credential: the Railway token is an environment variable the daemon supplies
to this process (`RAILWAY_TOKEN`, or `RAILWAY_API_TOKEN`) — never in the config
blob, never in a result, never logged.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from backend.deploy.adapter import DeployAdapter
from backend.deploy.contract import (
    Capability,
    DeploymentResult,
    DeploymentStatus,
    DeployTargetConfig,
    Environment,
)

_log = logging.getLogger("deploy.railway")

API_URL = "https://backboard.railway.com/graphql/v2"
TOKEN_ENV_VARS = ("RAILWAY_TOKEN", "RAILWAY_API_TOKEN")

#: Railway's DeploymentStatus enum -> our contract's states.
_STATUS_MAP = {
    "QUEUED": DeploymentStatus.PENDING,
    "WAITING": DeploymentStatus.PENDING,
    "INITIALIZING": DeploymentStatus.RUNNING,
    "BUILDING": DeploymentStatus.RUNNING,
    "DEPLOYING": DeploymentStatus.RUNNING,
    "SUCCESS": DeploymentStatus.LIVE,
    "SLEEPING": DeploymentStatus.LIVE,
    "FAILED": DeploymentStatus.FAILED,
    "CRASHED": DeploymentStatus.FAILED,
    "SKIPPED": DeploymentStatus.FAILED,
    "REMOVED": DeploymentStatus.ROLLED_BACK,
}

_Q_ME = "query { me { id email name } }"

_Q_PROJECT = """
query($id: String!) {
  project(id: $id) {
    services { edges { node { id name } } }
    environments { edges { node { id name } } }
  }
}
"""

_M_DEPLOY = """
mutation($environmentId: String!, $serviceId: String!, $commitSha: String) {
  serviceInstanceDeployV2(
    environmentId: $environmentId, serviceId: $serviceId, commitSha: $commitSha)
}
"""

_Q_DEPLOYMENT = """
query($id: String!) {
  deployment(id: $id) { id status url staticUrl }
}
"""

_Q_LOGS = """
query($id: String!, $limit: Int!) {
  buildLogs(deploymentId: $id, limit: $limit) { message }
  deploymentLogs(deploymentId: $id, limit: $limit) { message }
}
"""

_M_REMOVE = "mutation($id: String!) { deploymentRemove(id: $id) }"


class ApiError(RuntimeError):
    """Railway's API rejected the call, or was unreachable."""


class RailwayApi:
    """Thin GraphQL transport. The single seam tests replace with a fake —
    nothing else in this module touches the network."""

    def __init__(self, url: str = API_URL, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout

    def call(self, query: str, variables: dict, *, token: str) -> dict:
        """POST one GraphQL operation. Returns the `data` object. Raises
        `ApiError` on transport failure or a GraphQL `errors` payload."""
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise ApiError(f"railway API HTTP {exc.code}: {_body(exc)}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ApiError(f"railway API unreachable: {exc}") from exc
        except ValueError as exc:
            raise ApiError("railway API returned invalid JSON") from exc
        if payload.get("errors"):
            messages = "; ".join(
                str(e.get("message", e)) for e in payload["errors"])
            raise ApiError(f"railway API error: {messages}")
        return payload.get("data") or {}


class RailwayAdapter(DeployAdapter):
    """Deploys to Railway via its Public API. `test` vs `prod` selects the
    Railway environment; compose services map 1:1 to Railway services."""

    capabilities = frozenset({
        Capability.DEPLOY,
        Capability.STATUS,
        Capability.LOGS,
        Capability.PREVIEW_URL,
        Capability.TEARDOWN,
    })

    def __init__(self, api: RailwayApi | None = None, log_limit: int = 100) -> None:
        self.api = api or RailwayApi()
        self.log_limit = log_limit

    # ── credential ───────────────────────────────────────────────────────

    def verify_credential(self, token: str) -> tuple[bool, str]:
        token = (token or "").strip()
        if not token:
            return False, "no token provided"
        try:
            data = self.api.call(_Q_ME, {}, token=token)
        except ApiError as exc:
            return False, str(exc)
        me = data.get("me") or {}
        who = me.get("email") or me.get("name") or me.get("id")
        return True, f"authenticated as {who}" if who else "token accepted"

    # ── contract ─────────────────────────────────────────────────────────

    def deploy(self, target: DeployTargetConfig, ref: str) -> DeploymentResult:
        token = token_from_env()
        if not token:
            return _failed(f"no Railway token in env ({' or '.join(TOKEN_ENV_VARS)})")

        config = target.config or {}
        project_id = config.get("project_id")
        if not project_id:
            return _failed("deploy target config is missing project_id")

        try:
            services, environments = self._resolve(project_id, token)
            environment_id = _pick(environments, railway_environment(target),
                                   "environment")
            deployment_ids = [
                self._deploy_service(
                    _pick(services, name, "service"), environment_id, ref, token)
                for name in service_names(config)
            ]
        except (ApiError, LookupError) as exc:
            _log.warning("railway deploy failed: project=%s env=%s",
                         project_id, target.environment.value)
            return _failed(str(exc))

        primary = deployment_ids[0]
        deployment = self._deployment(primary, token)
        return DeploymentResult(
            deployment_id=primary,
            status=_status_of(deployment),
            url=_url_of(deployment),
            detail=(f"railway deploy {ref} -> {railway_environment(target)} "
                    f"({', '.join(service_names(config))})"),
        )

    def status(self, deployment_id: str) -> DeploymentStatus:
        token = token_from_env()
        if not token or not deployment_id:
            return DeploymentStatus.FAILED
        try:
            return _status_of(self._deployment(deployment_id, token))
        except ApiError:
            return DeploymentStatus.FAILED

    def logs(self, deployment_id: str) -> list[str]:
        token = token_from_env()
        if not token or not deployment_id:
            return []
        try:
            data = self.api.call(
                _Q_LOGS, {"id": deployment_id, "limit": self.log_limit}, token=token)
        except ApiError:
            return []
        lines = []
        for key in ("buildLogs", "deploymentLogs"):
            for entry in data.get(key) or []:
                message = (entry or {}).get("message", "")
                if message:
                    lines.append(message)
        return lines

    def preview_url(self, deployment_id: str) -> str | None:
        token = token_from_env()
        if not token or not deployment_id:
            return None
        try:
            return _url_of(self._deployment(deployment_id, token))
        except ApiError:
            return None

    def teardown(self, deployment_id: str) -> None:
        token = token_from_env()
        if not token or not deployment_id:
            return
        try:
            self.api.call(_M_REMOVE, {"id": deployment_id}, token=token)
        except ApiError:
            _log.warning("railway teardown failed: deployment=%s", deployment_id)

    # ── internals ────────────────────────────────────────────────────────

    def _resolve(self, project_id: str, token: str) -> tuple[dict, dict]:
        """name -> id for the project's services and environments. Railway's
        API is id-addressed; config carries human names (the compose service
        names), so every deploy resolves them once."""
        data = self.api.call(_Q_PROJECT, {"id": project_id}, token=token)
        project = data.get("project") or {}
        return (_by_name(project.get("services")),
                _by_name(project.get("environments")))

    def _deploy_service(self, service_id: str, environment_id: str,
                        ref: str, token: str) -> str:
        data = self.api.call(
            _M_DEPLOY,
            {"environmentId": environment_id, "serviceId": service_id,
             "commitSha": ref or None},
            token=token,
        )
        deployment_id = data.get("serviceInstanceDeployV2")
        if not deployment_id:
            raise ApiError(f"railway returned no deployment id for service {service_id}")
        return str(deployment_id)

    def _deployment(self, deployment_id: str, token: str) -> dict:
        data = self.api.call(_Q_DEPLOYMENT, {"id": deployment_id}, token=token)
        return data.get("deployment") or {}


# ── module helpers ───────────────────────────────────────────────────────

def token_from_env() -> str:
    """The Railway token the daemon supplied to this process. Never stored,
    never returned to a caller (ADR-011 §3)."""
    for var in TOKEN_ENV_VARS:
        token = (os.environ.get(var) or "").strip()
        if token:
            return token
    return ""


def railway_environment(target: DeployTargetConfig) -> str:
    """Railway environment name for this target's `test`/`prod`. Overridable
    per project via `config["environments"]`."""
    mapping = (target.config or {}).get("environments") or {}
    environment: Environment = target.environment
    return str(mapping.get(environment.value) or environment.value)


def service_names(config: dict) -> list[str]:
    """Compose services mapped 1:1 to Railway services. First = primary."""
    services = config.get("services") or (
        [config["service"]] if config.get("service") else [])
    return [str(s) for s in services] or ["app"]


def _by_name(connection) -> dict:
    """{name: id} from a Railway `{edges: [{node: {id, name}}]}` connection."""
    edges = (connection or {}).get("edges") or []
    return {
        node["name"]: node["id"]
        for node in (edge.get("node") or {} for edge in edges)
        if node.get("name") and node.get("id")
    }


def _pick(by_name: dict, name: str, kind: str) -> str:
    try:
        return by_name[name]
    except KeyError:
        known = ", ".join(sorted(by_name)) or "none"
        raise LookupError(
            f"no Railway {kind} named {name!r} in this project (have: {known})") from None


def _status_of(deployment: dict) -> DeploymentStatus:
    state = (deployment or {}).get("status") or ""
    return _STATUS_MAP.get(state.upper(), DeploymentStatus.FAILED)


def _url_of(deployment: dict) -> str | None:
    url = (deployment or {}).get("staticUrl") or (deployment or {}).get("url")
    if not url:
        return None
    return url if str(url).startswith("http") else f"https://{url}"


def _failed(detail: str) -> DeploymentResult:
    return DeploymentResult(
        deployment_id="", status=DeploymentStatus.FAILED, detail=detail)


def _body(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode()[:300]
    except Exception:  # noqa: BLE001 — a failed error-body read is not the error
        return exc.reason or ""
