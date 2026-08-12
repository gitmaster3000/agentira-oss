---
id: adding-a-feature
title: Adding a feature
sidebar_label: Adding a feature
---

# Adding a feature — the layering guide

Read this before adding a new domain to the backend. It shows where each kind
of code goes, using the **deploy settings** feature as the worked reference. The
same four layers apply to any feature.

The rules in `CLAUDE.md` ("Data Access", "Architecture") are the short form;
this is the walkthrough.

## The four layers

A request enters at the top and flows down. Each layer has one job and may only
call the layer directly below it.

```
REST route / MCP tool        transport: parse the request, shape the response
        │
        ▼
services.py (the gateway)     owns the DB session + commit; funnels every
        │                     channel (REST, MCP) to a handler; no domain logic
        ▼
handler (functions or class)  the domain logic + its own logger; operates on
        │                     the session the gateway hands it; never commits
        ▼
repos/<domain>.py             the DB handler: every .query(...).filter(...) and
        │                     write lives here; caller owns the commit
        ▼
adapter (only if pluggable)   provider-specific code, one class per provider,
                              selected at runtime from a registry
```

### 1. Transport — REST route / MCP tool

Thin. Parse the request body into a Pydantic model, call one `services.*`
function, translate exceptions into HTTP status codes. No business logic, no DB.

```python
# rest_api.py
class DeployCredentialUpdate(BaseModel):
    kind: str
    token: str

@projects.put("/{project_id}/deploy-credential")
def api_set_deploy_credential(project_id: str, body: DeployCredentialUpdate):
    try:
        return services.set_deploy_credential(
            project_id, kind=body.kind, token=body.token)
    except ValueError as e:
        raise HTTPException(400, str(e))
```

The MCP tool for the same feature calls the *same* `services.*` function. That
is the point of the gateway: one place both channels meet.

### 2. Gateway — `services.py`

`services.py` is the single entry point for REST and MCP. Its only jobs:

- open the DB session (`with _session() as db:`),
- own the transaction (`db.commit()` on success),
- delegate the actual work to a handler.

It holds **no** domain logic and does **no** SQL itself.

```python
# services.py
_deploy_manager = DeploymentManager()

def set_deploy_credential(project_id: str, *, kind: str, token: str) -> dict:
    with _session() as db:
        result = _deploy_manager.set_credential(db, project_id, kind=kind, token=token)
        db.commit()
        return result
```

### 3. Handler — functions, or a class when there's real polymorphism

The handler holds the domain logic: validation, orchestration, deciding what to
read and write. It receives the open session from the gateway and **never
commits** — the gateway owns the transaction boundary.

Default to a **module of functions** (`backend/<domain>.py`), like
`backend/attachments.py`. Reach for a **class** only when there is real
polymorphism to encapsulate — the deploy feature qualifies because each cloud
provider verifies credentials and deploys differently, so it has a
`DeploymentManager` and a per-provider adapter beneath it.

```python
# backend/deploy/manager.py
class DeploymentManager:
    def set_credential(self, db, project_id, *, kind, token) -> dict:
        project = self._require_project(db, project_id)       # PK fetch — see below
        kind = self._valid_kind(kind)                         # private validation
        valid, detail = self._verify_token(kind, token)       # delegates to adapter
        deploy_repo.set_credential(db, project.org_id, kind,  # write via the repo
                                   token=token or None, valid=valid,
                                   checked_at=_utcnow() if token else None)
        ...
```

### 4. DB handler — `repos/<domain>.py`

Every `db.query(...).filter(...)` and every write for the domain lives in one
repo module. Functions take the session (`db`); the caller owns the commit.
This keeps ORM internals, eager-loads, and dialect quirks out of the logic.

```python
# backend/forge/repos/deployments.py
def set_credential(db, org_id, kind, *, token, valid, checked_at) -> None:
    row = (db.query(DeployCredential)
             .filter(DeployCredential.org_id == org_id,
                     DeployCredential.kind == kind)
             .first())
    if row is None:
        row = DeployCredential(org_id=org_id, kind=kind)
        db.add(row)
    row.token, row.token_valid, row.token_checked_at = token, valid, checked_at
    db.flush()
```

**The one allowed shortcut:** a handler may fetch a row by primary key with
`db.get(Model, pk)` directly, without a repo function. That's an identity-map
lookup, not a query, and threading every PK fetch through a repo adds noise
without value. Anything with a `.filter(...)` — any real query — goes in the
repo. (`DeploymentManager._require_project` uses `db.get`; that's the boundary.)

### 5. Adapter — provider-specific code, only when pluggable

If the feature integrates with interchangeable external systems (cloud
providers, git hosts, runtimes), isolate everything provider-specific behind an
abstract adapter, one concrete class per provider, chosen at runtime from a
registry. **Nothing outside the adapter class names a specific provider.** Adding
a provider is then a new adapter class, never a schema migration or an `if
provider == "railway"` branch elsewhere.

```python
# backend/deploy/adapter.py  — the contract
class DeployAdapter(ABC):
    def verify_credential(self, token: str) -> tuple[bool, str]:
        return False, "credential verification not supported for this target"
    @abstractmethod
    def deploy(self, target, ref): ...

# backend/deploy/registry.py  — kind → adapter, nothing here knows a provider
def get_adapter(kind: TargetKind) -> DeployAdapter: ...
```

Storage stays generic to match: the deploy target is `kind` + an opaque
`config` blob on the project, and a credential is one row per `(org, kind)` — no
per-provider columns. The `kind` string is the only discriminator.

## Checklist for a new domain

1. **Model + migration** — new table/columns. Keep provider- or variant-specific
   detail in an opaque JSON/`config` column, not a column per variant.
2. **Repo** (`repos/<domain>.py`) — the queries and writes. Takes `db`, doesn't commit.
3. **Handler** — functions in `backend/<domain>.py`, or a class if there's real
   polymorphism. Domain logic only; operates on the passed `db`; no commit.
4. **Adapter + registry** — only if the feature has interchangeable backends.
5. **Gateway** (`services.py`) — thin functions: open session, delegate, commit.
   Both REST and MCP call these.
6. **Transport** — REST routes and/or MCP tools. Parse in, shape out, map errors.
7. **Tests** — against the real Postgres fixture (see `CLAUDE.md` → Testing).

## Why this shape

- One entry point (`services.py`) means REST and MCP can never drift — a fix
  applies to both channels at once.
- The transaction boundary lives in exactly one layer (the gateway), so a
  handler can't half-commit or leave a session open.
- SQL in one place per domain (the repo) keeps N+1 traps and schema coupling out
  of the logic and makes the logic testable.
- Provider code behind an adapter means the rest of the system stays
  provider-agnostic forever.
