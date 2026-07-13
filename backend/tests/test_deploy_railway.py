"""AP-318: RailwayAdapter tests. Railway's Public API is faked at the
transport seam — no network, no real token."""
from __future__ import annotations

import pytest

from backend.deploy.conformance import run_conformance_suite
from backend.deploy.contract import (
    Capability,
    DeploymentStatus,
    DeployTargetConfig,
    TargetKind,
)
from backend.deploy.railway import (
    ApiError,
    RailwayAdapter,
    railway_environment,
    service_names,
    token_from_env,
)
from backend.deploy.registry import get_adapter

DEPLOYMENT_ID = "dep_backend_1"


class FakeApi:
    """Stands in for Railway's GraphQL API. Stateful enough to be honest: a
    removed deployment reports REMOVED, like the real one does."""

    def __init__(self, state="SUCCESS", url="agentira-test.up.railway.app",
                 services=("backend", "frontend"), environments=("test", "production"),
                 raise_on=None):
        self.state = state
        self.url = url
        self.services = services
        self.environments = environments
        self.raise_on = raise_on or {}
        self.calls: list[dict] = []
        self.removed: set[str] = set()
        self._deployed = 0

    def call(self, query: str, variables: dict, *, token: str) -> dict:
        operation = _operation(query)
        self.calls.append({"op": operation, "vars": variables, "token": token})
        if operation in self.raise_on:
            raise self.raise_on[operation]
        return getattr(self, f"_{operation}")(variables)

    # one method per operation the adapter issues
    def _me(self, _):
        return {"me": {"id": "u1", "email": "ops@agentira.dev"}}

    def _project(self, _):
        return {"project": {
            "services": _edges(self.services, "svc"),
            "environments": _edges(self.environments, "env"),
        }}

    def _serviceInstanceDeployV2(self, variables):  # noqa: N802 — mirrors the GraphQL name
        self._deployed += 1
        return {"serviceInstanceDeployV2": f"dep_{variables['serviceId']}_{self._deployed}"}

    def _deployment(self, variables):
        deployment_id = variables["id"]
        if deployment_id in self.removed:
            return {"deployment": {"id": deployment_id, "status": "REMOVED"}}
        return {"deployment": {
            "id": deployment_id, "status": self.state, "staticUrl": self.url}}

    def _logs(self, _):
        return {
            "buildLogs": [{"message": "building..."}],
            "deploymentLogs": [{"message": "listening on :8000"}],
        }

    def _deploymentRemove(self, variables):  # noqa: N802 — mirrors the GraphQL name
        self.removed.add(variables["id"])
        return {"deploymentRemove": True}


def _edges(names, prefix):
    return {"edges": [{"node": {"id": f"{prefix}_{n}", "name": n}} for n in names]}


def _operation(query: str) -> str:
    """Which operation a query string is. Longest/most specific marker first —
    "deployment" is a substring of deploymentLogs/deploymentRemove."""
    markers = [
        ("serviceInstanceDeployV2(", "serviceInstanceDeployV2"),
        ("buildLogs(", "logs"),
        ("deploymentRemove(", "deploymentRemove"),
        ("deployment(", "deployment"),
        ("project(", "project"),
        ("me {", "me"),
    ]
    for marker, operation in markers:
        if marker in query:
            return operation
    raise AssertionError(f"unexpected query: {query}")


def _target(environment="test", **config):
    cfg = {"project_id": "proj_1", "services": ["backend", "frontend"], **config}
    return DeployTargetConfig(kind=TargetKind.RAILWAY, environment=environment, config=cfg)


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("RAILWAY_TOKEN", "rw_secret")
    return "rw_secret"


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch):
    """Nothing here may accidentally pick up a real token from the shell."""
    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    monkeypatch.delenv("RAILWAY_API_TOKEN", raising=False)


# ── deploy ───────────────────────────────────────────────────────────────

def test_deploy_returns_live_status_and_url(token):
    adapter = RailwayAdapter(api=FakeApi())

    result = adapter.deploy(_target(), ref="abc123")

    assert result.deployment_id == "dep_svc_backend_1"
    assert result.status == DeploymentStatus.LIVE
    assert result.url == "https://agentira-test.up.railway.app"


def test_deploy_sends_token_as_bearer_and_never_returns_it(token):
    api = FakeApi()
    adapter = RailwayAdapter(api=api)

    result = adapter.deploy(_target(), ref="abc123")

    assert {call["token"] for call in api.calls} == {"rw_secret"}
    assert "rw_secret" not in result.model_dump_json()


def test_deploy_without_token_fails_cleanly():
    result = RailwayAdapter(api=FakeApi()).deploy(_target(), ref="main")

    assert result.status == DeploymentStatus.FAILED
    assert "no Railway token" in result.detail


def test_deploy_without_project_id_fails_cleanly(token):
    target = DeployTargetConfig(kind=TargetKind.RAILWAY, config={"services": ["backend"]})

    result = RailwayAdapter(api=FakeApi()).deploy(target, ref="main")

    assert result.status == DeploymentStatus.FAILED
    assert "project_id" in result.detail


def test_deploy_maps_each_compose_service_one_to_one_and_deploys_the_ref(token):
    api = FakeApi()

    RailwayAdapter(api=api).deploy(_target(), ref="abc123")

    deploys = [call["vars"] for call in api.calls if call["op"] == "serviceInstanceDeployV2"]
    assert [d["serviceId"] for d in deploys] == ["svc_backend", "svc_frontend"]
    assert {d["commitSha"] for d in deploys} == {"abc123"}


def test_test_and_prod_select_railway_environments(token):
    api = FakeApi()
    adapter = RailwayAdapter(api=api)

    adapter.deploy(_target(environment="test"), ref="abc123")
    assert _first_deploy(api)["environmentId"] == "env_test"

    api.calls.clear()
    adapter.deploy(_target(environment="prod", environments={"prod": "production"}),
                   ref="abc123")
    assert _first_deploy(api)["environmentId"] == "env_production"


def test_unknown_service_name_fails_with_a_useful_message(token):
    api = FakeApi(services=("backend",))

    result = RailwayAdapter(api=api).deploy(_target(), ref="abc123")

    assert result.status == DeploymentStatus.FAILED
    assert "no Railway service named 'frontend'" in result.detail


def test_api_error_is_reported_as_failed_not_raised(token):
    api = FakeApi(raise_on={"serviceInstanceDeployV2": ApiError("railway API HTTP 402: over quota")})

    result = RailwayAdapter(api=api).deploy(_target(), ref="abc123")

    assert result.status == DeploymentStatus.FAILED
    assert "over quota" in result.detail


def _first_deploy(api):
    return next(c["vars"] for c in api.calls if c["op"] == "serviceInstanceDeployV2")


# ── status / logs / preview_url / teardown ───────────────────────────────

@pytest.mark.parametrize(("state", "expected"), [
    ("QUEUED", DeploymentStatus.PENDING),
    ("BUILDING", DeploymentStatus.RUNNING),
    ("DEPLOYING", DeploymentStatus.RUNNING),
    ("SUCCESS", DeploymentStatus.LIVE),
    ("CRASHED", DeploymentStatus.FAILED),
    ("REMOVED", DeploymentStatus.ROLLED_BACK),
])
def test_status_maps_railway_states(token, state, expected):
    adapter = RailwayAdapter(api=FakeApi(state=state))

    result = adapter.deploy(_target(), ref="abc123")

    assert result.status == expected
    assert adapter.status(result.deployment_id) == expected


def test_status_without_token_or_id_is_failed():
    adapter = RailwayAdapter(api=FakeApi())
    assert adapter.status("dep_1") == DeploymentStatus.FAILED  # no token in env


def test_status_survives_an_api_outage(token):
    adapter = RailwayAdapter(api=FakeApi(raise_on={"deployment": ApiError("unreachable")}))
    assert adapter.status(DEPLOYMENT_ID) == DeploymentStatus.FAILED


def test_logs_merges_build_and_runtime_logs(token):
    adapter = RailwayAdapter(api=FakeApi())

    assert adapter.logs(DEPLOYMENT_ID) == ["building...", "listening on :8000"]
    assert adapter.logs("") == []


def test_preview_url_none_when_no_domain_assigned(token):
    adapter = RailwayAdapter(api=FakeApi(url=None))

    result = adapter.deploy(_target(), ref="abc123")

    assert result.url is None
    assert adapter.preview_url(result.deployment_id) is None


def test_teardown_removes_the_deployment_and_leaves_it_non_live(token):
    api = FakeApi()
    adapter = RailwayAdapter(api=api)
    result = adapter.deploy(_target(), ref="abc123")

    adapter.teardown(result.deployment_id)

    assert api.removed == {result.deployment_id}
    assert adapter.status(result.deployment_id) == DeploymentStatus.ROLLED_BACK
    assert adapter.preview_url(result.deployment_id) is None


def test_teardown_swallows_api_errors(token):
    adapter = RailwayAdapter(api=FakeApi(raise_on={"deploymentRemove": ApiError("gone")}))
    adapter.teardown(DEPLOYMENT_ID)  # must not raise


# ── credential verification ──────────────────────────────────────────────

def test_verify_credential_ok():
    valid, detail = RailwayAdapter(api=FakeApi()).verify_credential("rw_secret")
    assert valid is True
    assert detail == "authenticated as ops@agentira.dev"


def test_verify_credential_rejects_bad_token():
    api = FakeApi(raise_on={"me": ApiError("railway API HTTP 401: Unauthorized")})

    valid, detail = RailwayAdapter(api=api).verify_credential("bad")

    assert valid is False
    assert "Unauthorized" in detail


def test_verify_credential_rejects_empty_token():
    assert RailwayAdapter(api=FakeApi()).verify_credential("") == (False, "no token provided")


# ── contract conformance + registry ──────────────────────────────────────

def test_railway_adapter_passes_conformance_suite(token):
    run_conformance_suite(RailwayAdapter(api=FakeApi()), _target(), ref="abc123")


def test_railway_adapter_implements_every_capability():
    adapter = RailwayAdapter(api=FakeApi())
    for capability in (Capability.DEPLOY, Capability.STATUS, Capability.LOGS,
                       Capability.PREVIEW_URL, Capability.TEARDOWN):
        assert adapter.supports(capability)


def test_railway_adapter_is_registered():
    import backend.deploy  # noqa: F401 — import registers the adapter

    assert isinstance(get_adapter(TargetKind.RAILWAY), RailwayAdapter)


# ── config helpers ───────────────────────────────────────────────────────

def test_token_from_env_accepts_either_variable(monkeypatch):
    assert token_from_env() == ""
    monkeypatch.setenv("RAILWAY_API_TOKEN", "alt")
    assert token_from_env() == "alt"


def test_service_names_defaults_and_singular_form():
    assert service_names({}) == ["app"]
    assert service_names({"service": "backend"}) == ["backend"]
    assert service_names({"services": ["a", "b"]}) == ["a", "b"]


def test_railway_environment_defaults_to_the_environment_value():
    assert railway_environment(_target(environment="prod")) == "prod"
