# Deploy tab — backend requirements

The Deploy frontend (`src/pages/Deploy.jsx`, `src/components/deploy/*`) is built and
merged against the contract below. This document is the spec the backend matches.
Every endpoint the UI calls already exists as a stub in `src/api.js` under the
`// Deploy` comment.

**Implementation status** (backend repo):

| endpoint | status |
|---|---|
| `POST /deploy/provider/verify` | **live** — AP-446, `backend/deploy/railway.py` |
| everything else below | **live** — AP-451, `backend/deploy/flow.py` + `backend/rest_api.py` |

The full contract is wired through `services.py` → `DeployFlow` → the adapter
registry, backed by the `deployments` table, and covered end-to-end by
`backend/tests/test_deploy_flow.py` (Railway adapter faked) and the
`bruno/rest/11-deploy` collection. Two honest caveats for this build:

- **Branch enumeration** is derived from persisted deployments (plus `main`),
  not a live GitHub branch listing — a project shows `main` and any branch it
  has deployed. Full repo-branch/commit enrichment needs the GitHub App.
- **`repo-access`** reports `granted` optimistically (no live GitHub App
  install probe yet), and the **live-Railway build path** is wired through the
  adapter but not exercised against a real Railway account here — that needs a
  real token + service linkage (`RAILWAY_API_KEY`).

All routes are relative to the existing API base (`/api`) and authenticate with
the same bearer JWT as the rest of the app. `project_id` is the Agentira project.

---

## 1. Model

### `DeployConnection` — one per project, at most

| field | type | notes |
|---|---|---|
| `connected` | bool | `false` when no provider is attached; the UI shows the empty state |
| `provider` | `"railway" \| "gcp" \| "docker"` | only `railway` is live; the other two render as "COMING" |
| `repo` | string | `owner/name` of the repo the provider builds from |
| `service_name` | string | provider-side service that hosts `main` |
| `service_region` | string \| null | shown as `billing-api · us-west` |
| `key_valid` | bool | result of the most recent probe |
| `key_checked_at` | ISO 8601 | drives "Key last checked · 2 min ago" |
| `connected_at` | ISO 8601 | drives "connected 8 days ago" |

**The API key is never returned.** It is write-only: accepted on verify/connect,
stored encrypted at rest, and thereafter only ever referenced by the server.

### `Deployment`

| field | type | notes |
|---|---|---|
| `id` | string | |
| `status` | `queued \| building \| live \| failed \| crashed \| stopped` | the six pills the UI renders. Any other value degrades to "No preview" |
| `url` | string \| null | `https://…` — required when `status == "live"`, else null |
| `step` | int \| null | current build step, only while `building` |
| `total_steps` | int \| null | e.g. 4 → the pill reads "Building · 2/4" |
| `status_reason` | string | **required, non-empty.** See §4 |
| `trigger` | `push \| manual \| preview` | `manual` flips the byline to "redeployed by" |
| `updated_at` | ISO 8601 | drives the relative timestamps |
| `events` | `[{status, at}]` | status timeline shown above the logs |

### `BranchEntry` — what the list is actually made of

| field | type | notes |
|---|---|---|
| `branch` | string | |
| `is_main` | bool | main is never offered a "Stop" button |
| `commit_sha` | string | full sha; UI truncates to 7 |
| `commit_message` | string | |
| `author` | string | agent name or human handle |
| `author_is_agent` | bool | renders the small `AI` avatar |
| `committed_at` | ISO 8601 | |
| `deployment` | `Deployment \| null` | `null` = branch has never been deployed |

---

## 2. Endpoints

### Provider

```
GET    /projects/{project_id}/deploy/provider
→ 200 DeployConnection            (or {"connected": false} when none)
```

```
POST   /projects/{project_id}/deploy/provider/verify
body   { "provider": "railway", "api_key": "…" }
→ 200  { "valid": true,  "account": "acme-prod",
         "services": [ { "id": "svc_1", "name": "billing-api",
                         "type": "web service", "region": "us-west",
                         "deployable": true } ] }
→ 200  { "valid": false, "error": { "headline": "Railway rejected this key (401)",
                                     "detail": "It may be expired or revoked. Generate a fresh token in Railway → Account → Tokens." } }
```

Note the shape: an **invalid key is a 200, not a 4xx**. The wizard renders
`error.headline` and `error.detail` inline; a transport-level failure (5xx,
timeout) is a separate, uglier path. `deployable: false` rows (a Postgres add-on,
say) render disabled and cannot be selected.

The key is probed exactly once here. The UI never retries on its own.

```
GET    /projects/{project_id}/deploy/provider/repo-access?provider=railway
→ 200  { "repo": "acme/billing-api", "granted": false,
         "install_url": "https://github.com/apps/railway/installations/new?…" }
```

Step 2 of the wizard polls this every 3 seconds while `granted` is false — the
user is in another tab completing a GitHub App install. The step cannot be
skipped: the "Continue" button does not exist until `granted` is true.

```
POST   /projects/{project_id}/deploy/provider
body   { "provider": "railway", "api_key": "…", "repo": "acme/billing-api", "service_id": "svc_1" }
→ 201  DeployConnection
```

Connecting should also kick off the first deploy of `main`; the UI drops straight
into the Deploy home expecting to see a `building` deployment.

```
POST   /projects/{project_id}/deploy/provider/reverify   → 200 DeployConnection
DELETE /projects/{project_id}/deploy/provider            → 204
```

Disconnect must also tear down any live previews this project owns.

### Deployments

```
GET    /projects/{project_id}/deployments
→ 200  { "branches": [ BranchEntry, … ] }
```

One entry per *active branch in the repo*, not one per deployment — a branch with
no deployment still appears (with `deployment: null`) so the user can preview it.
`main` first, then most-recently-committed. Cap the response at a sane number of
branches (the UI paginates client-side at 8 and shows "Show N more").

```
POST   /projects/{project_id}/deployments
body   { "branch": "feat/usage-metering" }
→ 202  Deployment                    // status: "queued"
```

Deploys `main` when `branch == "main"`, otherwise spins up an on-demand preview.
Idempotent per branch: a second call while one is `queued`/`building` returns the
in-flight deployment rather than starting a second.

```
POST   /projects/{project_id}/deployments/{id}/redeploy  → 202 Deployment
DELETE /projects/{project_id}/deployments/{id}           → 204   // teardown → status "stopped"
```

`DELETE` on a `main` deployment should be rejected (409) — the UI never offers it,
but the API shouldn't rely on that.

```
GET    /projects/{project_id}/deployments/{id}/logs?cursor=0
→ 200  { "lines": [ { "level": "error", "text": "npm ci failed — lockfile out of sync" } ],
         "next_cursor": 128, "done": false }
```

Cursor-paginated, append-only. `cursor` is an opaque integer offset the client
echoes back; return only lines after it. `done: true` when the deployment has
reached a terminal status and no more lines will arrive. `level` is one of
`error | warn | info | debug` and drives the line colour.

The logs panel polls every 3 seconds while the deployment is `queued` or
`building`, then stops. Server-Sent Events would be a strict improvement here and
the panel can be adapted to it, but cursor polling is what ships first.

---

## 3. Polling contract

The Deploy page polls `GET /deployments` every **6 seconds**, and only while at
least one branch is `queued` or `building`. Once everything settles the interval
is torn down; the tab also pauses while the document is hidden. A project sitting
on a green `main` generates zero background traffic.

The backend does not need to push. It does need `GET /deployments` to be cheap.

---

## 4. Transparency is a requirement, not a nicety

`status_reason` is not optional and must never be an empty string. Agentira's
whole ethos is "no black boxes" — a deployment must never just silently change
colour. The UI renders this string verbatim on the Live card. Examples of what
the backend should send:

| status | `status_reason` |
|---|---|
| `queued` | `Queued — waiting for a build slot.` |
| `building` | `Installing dependencies… · step 2 of 4 · polling every 5s` |
| `live` | `Deployed in 47s from push to main · healthy for 6 min` |
| `live` (preview) | `Preview live · healthy for 12 min · torn down 24h after last push` |
| `failed` | `Build error: npm ci failed — lockfile out of sync` |
| `crashed` | `Exited with code 1 four minutes after deploy — see runtime logs` |
| `stopped` | `Preview torn down after 24h idle · redeploy to bring it back` |

Cause belongs on the card, not in a tooltip. The frontend has a fallback string
per status (`reasonFor()` in `LivePreview.jsx`) so the line is never blank, but
that fallback is generic and the backend should always beat it.

---

## 5. Edge cases the UI already handles

Each of these has a rendered state waiting for the backend to produce it:

- **No provider connected** — `{"connected": false}` → the "Ship this project live" empty state.
- **Connected, main never deployed** — every `BranchEntry.deployment` is `null` → the "No deploy yet" card with a *Deploy main now* button.
- **Invalid / expired key** — `verify` returns `valid: false` with an `error` object; a *stored* key going bad is `key_valid: false` on the connection, which surfaces a "Deployments are paused" warning in Provider settings.
- **Repo access not granted** — `repo-access` returns `granted: false` + `install_url`.
- **Build failed / app crashed** — `failed` / `crashed` status with a `status_reason` and a *View logs* button on the reason line.
- **Preview torn down** — `stopped`, offered a *Redeploy preview* button.
- **Many branches** — the list shows 8 and expands on demand.

---

## 6. Out of scope for this build

Per the design brief: Agentira-hosted zero-key defaults, automatic per-PR
previews (previews are on-demand only), and multi-region / scaling / infra config
knobs. GCP and Docker are shaped identically but render as "COMING" and have no
connect path.

---

## 7. Security notes

- The API key is accepted over TLS, encrypted at rest, and never returned by any
  endpoint — including `GET /deploy/provider`. The wizard's field is
  `type="password"` and clears on unmount.
- The Live card renders the deployed app in a sandboxed iframe
  (`allow-scripts allow-forms allow-same-origin allow-popups`). Deployed apps are
  first-party user code, but the sandbox attribute is deliberate; don't widen it
  without a reason.
- `url` must be `https://`. The frontend links it directly and embeds it; an
  `http://` value would be blocked as mixed content anyway.
- Repo access is a real GitHub App install. There is no skip path in the UI and
  there should be none in the API.
