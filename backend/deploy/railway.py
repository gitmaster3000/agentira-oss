"""AP-318: `RailwayAdapter` — the first real deploy adapter (ADR-011 §2).

Talks to Railway's **Public GraphQL API** (`backboard.railway.com/graphql/v2`),
not the `railway` CLI: the backend runs as a container image on Railway, where
no CLI binary exists and there's no local working directory to `railway up`.
The API deploys a *ref* of the service's connected repo, which is exactly what
a deploy of a task's branch means here. Stdlib urllib only, same shape as
`backend/repo_tokens.py` / `github_deployments.py`.

Operations used (Railway Public API):

    me                                   verify a personal token
    projects                             verify a team token (`me` is personal-only)
    projectToken                         verify a project token (one project + env)
    serviceInstanceDeployV2              deploy a commit/branch to an env
    deployment(id)                       status, url/staticUrl
    buildLogs / deploymentLogs           logs
    deploymentRemove(id)                 teardown
    project(id)                          resolve service/environment names -> ids
    project(id).environments(isEphemeral) the PR (preview) environments

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

Token kinds: account and workspace (team) tokens go in `Authorization: Bearer`.
A *project* token (Project → Settings → Tokens) is scoped to one project and one
environment and must go in `Project-Access-Token` instead. The adapter detects
the kind once per token (cached by hash, never the raw token) and, for a project
token, deploys to the token's own environment; `project_id` defaults to the
token's project.

Branch previews ride on Railway's *PR Environments* (a project setting): Railway
creates an ephemeral environment per pull request and builds it. `main` deploys
to the base environment; any other branch deploys into its PR environment, and
`previews()` reports what Railway already built so the UI shows it without a
click. A project token can't see other environments, so it deploys `main` only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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

#: Cloudflare fronts Railway's API and 403s the stdlib default
#: `Python-urllib/3.x` UA. Send a real one or nothing gets through.
USER_AGENT = "agentira-deploy/1.0 (+https://agentira.dev)"
_CLOUDFLARE_BLOCK = "error code: 1010"

#: Railway phrasing for "your token doesn't grant this". Anything else is ours.
_AUTH_MESSAGES = ("not authorized", "unauthorized", "invalid token",
                  "authentication", "forbidden")

#: The branch that deploys to the base environment. Any other
#: `config["branch"]` is a preview and deploys into its Railway PR environment.
BASE_BRANCH = "main"

_SHA = re.compile(r"[0-9a-f]{40}")

_NO_PREVIEW_ENVIRONMENT = (
    "No preview environment for {branch} yet. Open a pull request for this "
    "branch: Railway builds a preview for each one once PR Environments is "
    "turned on in the Railway project's settings.")

_PROJECT_TOKEN_NO_PREVIEWS = (
    "This key is a Railway project token, which only reaches one environment, "
    "so it can't deploy previews of other branches. Connect a workspace token "
    "(Railway → Workspace → Tokens) to get a preview for each pull request.")

#: Railway services that host no app of ours — the wizard shows them disabled.
_ADDON_HINTS = ("postgres", "mysql", "redis", "mongo", "clickhouse", "minio")

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

#: Only a project token can run this; it names the one project + environment
#: the token is scoped to.
_Q_PROJECT_TOKEN = "query { projectToken { projectId environmentId } }"

#: Works for every token type; `me` does not (see `verify_credential`).
_Q_PROJECTS = "query { projects(first: 1) { edges { node { id } } } }"

#: What the connect wizard lists: every project the key can see, and its
#: services. Same query for a personal or a team key.
_Q_WORKSPACE = """
query {
  projects(first: 20) {
    edges { node {
      id
      name
      services { edges { node { id name } } }
    } }
  }
}
"""

_Q_PROJECT = """
query($id: String!) {
  project(id: $id) {
    name
    baseEnvironmentId
    primaryEnvironmentId
    services { edges { node { id name } } }
    environments(isEphemeral: false) { edges { node { id name } } }
  }
}
"""

#: Railway's PR environments: one ephemeral environment per open pull request,
#: tagged with the PR's branch, and the latest deployment of each service.
_Q_PREVIEWS = """
query($id: String!) {
  project(id: $id) {
    environments(isEphemeral: true) { edges { node {
      id
      meta { branch prNumber }
      serviceInstances { edges { node {
        serviceName
        latestDeployment { id status url staticUrl }
      } } }
    } } }
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


class AuthError(ApiError):
    """Railway looked at the token and refused it. The only error that means
    "this token is bad" — everything else is our problem, not the user's."""


class TransportError(ApiError):
    """We never got a usable answer: unreachable, timed out, or non-JSON."""


class BlockedError(TransportError):
    """An edge/WAF (Cloudflare) refused the request before Railway saw it.
    Says nothing about the token — hence a TransportError, not an AuthError."""


class RailwayApi:
    """Thin GraphQL transport. The single seam tests replace with a fake —
    nothing else in this module touches the network."""

    def __init__(self, url: str = API_URL, timeout: float = 30.0) -> None:
        self.url = url
        self.timeout = timeout

    def call(self, query: str, variables: dict, *, token: str,
             project_token: bool = False) -> dict:
        """POST one GraphQL operation. Returns the `data` object. Raises
        `AuthError` if Railway refused the token, `TransportError`/`BlockedError`
        if we never got an answer, `ApiError` for anything else.
        `project_token` sends the token as `Project-Access-Token` (Railway's
        header for project tokens) instead of `Authorization: Bearer`."""
        operation = _operation_name(query)
        body = json.dumps({"query": query, "variables": variables}).encode()
        auth = ({"Project-Access-Token": token} if project_token
                else {"Authorization": f"Bearer {token}"})
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                **auth,
                "Content-Type": "application/json",
                # Railway is behind Cloudflare, which 403s the stdlib default
                # `Python-urllib/3.x` UA with "error code: 1010". Identify
                # ourselves or every request dies before reaching the API.
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise self._http_error(operation, exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            _log.warning("railway %s unreachable: %s", operation, exc)
            raise TransportError(f"railway API unreachable: {exc}") from exc
        except ValueError as exc:
            _log.warning("railway %s returned non-JSON", operation)
            raise TransportError("railway API returned invalid JSON") from exc

        if payload.get("errors"):
            messages = "; ".join(
                str(e.get("message", e)) for e in payload["errors"])
            _log.warning("railway %s error: %s", operation, messages)
            if _is_auth_message(messages):
                raise AuthError(f"railway API error: {messages}")
            raise ApiError(f"railway API error: {messages}")

        _log.debug("railway %s ok", operation)
        return payload.get("data") or {}

    def _http_error(self, operation: str, exc: urllib.error.HTTPError) -> ApiError:
        """Classify an HTTP failure. Never logs the token or the auth header."""
        body = _body(exc)
        _log.warning("railway %s HTTP %s: %s", operation, exc.code, body.strip()[:200])
        if _CLOUDFLARE_BLOCK in body:
            return BlockedError(
                f"railway API HTTP {exc.code}: blocked by Railway's edge "
                f"({_CLOUDFLARE_BLOCK}) — the request never reached the API")
        if exc.code in (401, 403):
            return AuthError(f"railway API HTTP {exc.code}: {body.strip()}")
        if exc.code >= 500:
            return TransportError(f"railway API HTTP {exc.code}: {body.strip()}")
        return ApiError(f"railway API HTTP {exc.code}: {body.strip()}")


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
        #: sha256(token) -> a project token's {projectId, environmentId}, or
        #: None for an account/workspace token. Never keyed by the raw token.
        self._scopes: dict[str, dict | None] = {}

    # ── credential ───────────────────────────────────────────────────────

    def verify_credential(self, token: str) -> tuple[bool | None, str]:
        """(valid, detail). `None` means *we* couldn't check — Railway was
        unreachable or an edge blocked us — which is not the user's token being
        bad, and must never be shown as "invalid"."""
        token = (token or "").strip()
        if not token:
            return False, "no token provided"
        try:
            data = self.api.call(_Q_ME, {}, token=token)
        except TransportError as exc:
            _log.warning("railway credential unverifiable: %s", exc)
            return None, f"could not reach Railway to check this key: {exc}"
        except AuthError as exc:
            # A workspace/team token authenticates fine but has no user behind
            # it, so Railway refuses `me`. Re-probe with a query every token
            # type can run before calling the token bad.
            return self._verify_team_token(token, personal_error=exc)
        except ApiError as exc:
            _log.warning("railway credential unverifiable: %s", exc)
            return None, f"could not check this key with Railway: {exc}"

        self._scopes[_token_key(token)] = None
        me = data.get("me") or {}
        who = me.get("email") or me.get("name") or me.get("id")
        _log.info("railway credential verified (personal token)")
        return True, f"authenticated as {who}" if who else "token accepted"

    def _verify_team_token(self, token: str, *,
                           personal_error: AuthError) -> tuple[bool | None, str]:
        try:
            self.api.call(_Q_PROJECTS, {}, token=token)
        except TransportError as exc:
            _log.warning("railway credential unverifiable: %s", exc)
            return None, f"could not reach Railway to check this key: {exc}"
        except AuthError:
            # Not an account/workspace token either. A project token is refused
            # by both Bearer probes — it needs its own header.
            return self._verify_project_token(token, personal_error=personal_error)
        except ApiError:
            _log.info("railway rejected the credential")
            return False, str(personal_error)
        self._scopes[_token_key(token)] = None
        _log.info("railway credential verified (team token)")
        return True, "authenticated (team token)"

    def _verify_project_token(self, token: str, *,
                              personal_error: AuthError) -> tuple[bool | None, str]:
        try:
            scope = self._project_scope(token)
        except TransportError as exc:
            _log.warning("railway credential unverifiable: %s", exc)
            return None, f"could not reach Railway to check this key: {exc}"
        if scope is None:
            _log.info("railway rejected the credential")
            return False, str(personal_error)
        self._scopes[_token_key(token)] = scope
        _log.info("railway credential verified (project token)")
        return True, "authenticated (project token)"

    def probe_key(self, token: str) -> dict:
        """What the connect wizard needs from one key: is it good, whose
        workspace is it, and which services can we deploy to. Shape is the
        `deploy/provider/verify` contract (frontend/docs/deploy-backend-
        requirements.md §2) — an unusable key is a result, not an exception."""
        valid, detail = self.verify_credential(token)
        if valid is not True:
            return {"valid": False, "error": _verify_error(valid, detail)}
        token = token.strip()
        try:
            scope = self._scope(token)
            if scope:
                # A project token can't list projects — only its own one.
                data = self._call(_Q_PROJECT, {"id": scope["projectId"]}, token)
                projects = [data.get("project") or {}]
            else:
                data = self._call(_Q_WORKSPACE, {}, token)
                projects = _nodes(data.get("projects"))
        except ApiError as exc:
            return {"valid": False, "error": _verify_error(None, str(exc))}

        services = [
            {
                "id": service["id"],
                "name": service["name"],
                "project": project.get("name") or "",
                "project_id": project.get("id") or (scope or {}).get("projectId"),
                "type": "database" if _is_addon(service["name"]) else "web service",
                "region": None,
                "deployable": not _is_addon(service["name"]),
            }
            for project in projects
            for service in _nodes(project.get("services"))
            if service.get("id") and service.get("name")
        ]
        _log.info("railway key probe ok: %s project(s), %s service(s)",
                  len(projects), len(services))
        account = (_project_account(projects[0], scope["environmentId"]) if scope
                   else _account_of(projects, detail))
        return {"valid": True, "account": account, "services": services}

    # ── contract ─────────────────────────────────────────────────────────

    def deploy(self, target: DeployTargetConfig, ref: str) -> DeploymentResult:
        token = token_from_env()
        if not token:
            return _failed(f"no Railway token in env ({' or '.join(TOKEN_ENV_VARS)})")

        config = target.config or {}
        project_id = config.get("project_id")
        environment = railway_environment(target)
        try:
            # A project token is bound to one project + environment: deploy
            # there, whatever the target's test/prod mapping says.
            scope = self._scope(token)
            project_id = project_id or (scope or {}).get("projectId")
            if not project_id:
                return _failed("deploy target config is missing project_id")
            branch = config.get("branch")
            if branch and branch != BASE_BRANCH:
                if scope:
                    return _failed(_PROJECT_TOKEN_NO_PREVIEWS)
                environment_id, environment = self._preview_environment(
                    project_id, branch, token)
                services, _environments, _base = self._resolve(project_id, token)
            elif scope:
                services, environments, _base = self._resolve(project_id, token)
                environment_id = scope["environmentId"]
                environment = _name_of(environments, environment_id)
            else:
                services, environments, base = self._resolve(project_id, token)
                if environment not in environments and base and not config.get("environments"):
                    # No explicit test/prod mapping: `main` goes to the
                    # project's base environment (the one PRs fork from).
                    environment_id, environment = base, _name_of(environments, base)
                else:
                    environment_id = _pick(environments, environment, "environment")
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
            detail=(f"railway deploy {ref} -> {environment} "
                    f"({', '.join(service_names(config))})"),
        )

    def previews(self, target: DeployTargetConfig) -> dict[str, DeploymentResult]:
        """{branch: latest deployment} of the primary service in each Railway
        PR environment — previews Railway built on its own when a PR opened or
        got a push. `{}` for a project token (it can't see other environments).
        Raises `ApiError` when Railway can't be asked; the caller decides."""
        token = token_from_env()
        project_id = (target.config or {}).get("project_id")
        if not token or not project_id or self._scope(token):
            return {}
        primary = service_names(target.config or {})[0]
        found = {}
        for env in self._pr_environments(project_id, token):
            branch = (env.get("meta") or {}).get("branch")
            deployment = next(
                (inst.get("latestDeployment") for inst in _nodes(env.get("serviceInstances"))
                 if inst.get("serviceName") == primary), None)
            if not branch or not (deployment or {}).get("id"):
                continue
            pr_number = (env.get("meta") or {}).get("prNumber")
            found[branch] = DeploymentResult(
                deployment_id=str(deployment["id"]),
                status=_status_of(deployment),
                url=_url_of(deployment),
                detail=(f"Preview of pull request #{pr_number}" if pr_number
                        else "Preview built by Railway"),
            )
        return found

    def observe(self, deployment_id: str) -> DeploymentResult:
        """Fresh status + URL of one deployment. Unlike `status()`, raises
        `ApiError` when Railway can't be asked — "couldn't check" must not
        overwrite a building deployment with "failed"."""
        token = token_from_env()
        if not token:
            raise ApiError("no Railway token in env")
        deployment = self._deployment(deployment_id, token)
        return DeploymentResult(deployment_id=deployment_id,
                                status=_status_of(deployment), url=_url_of(deployment))

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
            data = self._call(
                _Q_LOGS, {"id": deployment_id, "limit": self.log_limit}, token)
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
            self._call(_M_REMOVE, {"id": deployment_id}, token)
        except ApiError:
            _log.warning("railway teardown failed: deployment=%s", deployment_id)

    # ── internals ────────────────────────────────────────────────────────

    def _call(self, query: str, variables: dict, token: str) -> dict:
        """One API call with the header this token's kind needs."""
        return self.api.call(query, variables, token=token,
                             project_token=self._scope(token) is not None)

    def _scope(self, token: str) -> dict | None:
        """The token's project-token scope, detected once per token."""
        key = _token_key(token)
        if key not in self._scopes:
            self._scopes[key] = self._project_scope(token)
        return self._scopes[key]

    def _project_scope(self, token: str) -> dict | None:
        """{projectId, environmentId} if Railway accepts this as a project
        token, else None (an account/workspace token). A transport failure
        raises — "couldn't ask" is not an answer, so it is never cached."""
        try:
            data = self.api.call(_Q_PROJECT_TOKEN, {}, token=token, project_token=True)
        except TransportError:
            raise
        except ApiError:
            return None
        scope = data.get("projectToken") or {}
        if scope.get("projectId") and scope.get("environmentId"):
            return {"projectId": scope["projectId"],
                    "environmentId": scope["environmentId"]}
        return None

    def _resolve(self, project_id: str, token: str) -> tuple[dict, dict, str | None]:
        """name -> id for the project's services and (non-preview)
        environments, plus the base environment id. Railway's API is
        id-addressed; config carries human names (the compose service names),
        so every deploy resolves them once."""
        data = self._call(_Q_PROJECT, {"id": project_id}, token)
        project = data.get("project") or {}
        return (_by_name(project.get("services")),
                _by_name(project.get("environments")),
                project.get("baseEnvironmentId") or project.get("primaryEnvironmentId"))

    def _pr_environments(self, project_id: str, token: str) -> list[dict]:
        data = self._call(_Q_PREVIEWS, {"id": project_id}, token)
        return _nodes((data.get("project") or {}).get("environments"))

    def _preview_environment(self, project_id: str, branch: str,
                             token: str) -> tuple[str, str]:
        """(id, label) of the PR environment Railway made for `branch`."""
        for env in self._pr_environments(project_id, token):
            meta = env.get("meta") or {}
            if meta.get("branch") == branch and env.get("id"):
                label = (f"pull request #{meta['prNumber']}" if meta.get("prNumber")
                         else f"preview of {branch}")
                return env["id"], label
        raise LookupError(_NO_PREVIEW_ENVIRONMENT.format(branch=branch))

    def _deploy_service(self, service_id: str, environment_id: str,
                        ref: str, token: str) -> str:
        data = self._call(
            _M_DEPLOY,
            # A branch name is not a commit. Without a sha Railway builds the
            # latest commit of the branch that environment tracks.
            {"environmentId": environment_id, "serviceId": service_id,
             "commitSha": ref if _SHA.fullmatch(ref or "") else None},
            token,
        )
        deployment_id = data.get("serviceInstanceDeployV2")
        if not deployment_id:
            raise ApiError(f"railway returned no deployment id for service {service_id}")
        return str(deployment_id)

    def _deployment(self, deployment_id: str, token: str) -> dict:
        data = self._call(_Q_DEPLOYMENT, {"id": deployment_id}, token)
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


def _token_key(token: str) -> str:
    """Cache key for a token — a digest, so the raw secret is never retained."""
    return hashlib.sha256(token.encode()).hexdigest()


def _operation_name(query: str) -> str:
    """Best-effort label for a log line — the first field in the selection set
    (`me`, `projects`, `deployment`, …). Diagnostics only; never parsed."""
    match = re.search(r"\{\s*(\w+)", query)
    return match.group(1) if match else "query"


def _is_auth_message(messages: str) -> bool:
    lowered = messages.lower()
    return any(hint in lowered for hint in _AUTH_MESSAGES)


def _is_addon(service_name: str) -> bool:
    lowered = service_name.lower()
    return any(hint in lowered for hint in _ADDON_HINTS)


def _nodes(connection) -> list[dict]:
    """The `node` objects of a Railway `{edges: [{node: …}]}` connection."""
    return [edge.get("node") or {} for edge in (connection or {}).get("edges") or []]


def _account_of(projects: list[dict], detail: str) -> str:
    """A human label for whose Railway this key opens. A personal key gives us
    the email; a team key gives us only what it can see."""
    if detail.startswith("authenticated as "):
        return detail[len("authenticated as "):]
    return projects[0].get("name") or "Railway workspace" if projects else "Railway workspace"


def _name_of(environments: dict, environment_id: str) -> str:
    return next((name for name, env_id in environments.items()
                 if env_id == environment_id), environment_id)


def _project_account(project: dict, environment_id: str) -> str:
    """"<project> · <environment>" for a project token — all it can see."""
    names = {env_id: name for name, env_id in _by_name(project.get("environments")).items()}
    label = project.get("name") or "Railway project"
    return f"{label} · {names[environment_id]}" if environment_id in names else label


def _verify_error(valid: bool | None, detail: str) -> dict:
    """The wizard renders `headline` + `detail` inline. Say plainly whether the
    key is bad or we simply couldn't check it — those are different problems and
    only one of them is the user's to fix."""
    if valid is None:
        return {
            "headline": "Couldn't reach Railway to check this key",
            "detail": (f"{detail} This is not a problem with your key — "
                       "try again in a moment."),
        }
    return {
        "headline": "Railway rejected this key",
        "detail": (f"{detail} It may be expired or revoked. Generate a fresh "
                   "token in Railway → Account → Tokens, your workspace's "
                   "Tokens tab, or Project → Settings → Tokens, and paste it "
                   "here."),
    }


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
