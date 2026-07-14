# Bruno collections

`rest/` and `mcp/` are integration suites that run against a live instance.

## Environments

| env | base_url |
|---|---|
| `ci` | `http://localhost:8000` — a local backend |
| `pre-prod` | `https://flowty-api-pre-prod.up.railway.app` |

## Secrets

No secret is ever committed. Environment files reference `process.env`, and the
values live in `bruno/.env` (git-ignored):

```
AGENTIRA_ADMIN_PASSWORD=…   # admin login on the target instance
RAILWAY_API_KEY=…           # a Railway workspace token (deploy suite only)
```

Both are readable from Railway itself — they are variables on the `flowty-api`
service — so a fresh checkout can repopulate `.env` without anyone passing
secrets around by hand:

```bash
railway variables --service flowty-api --environment pre-prod
```

## Running

```bash
cd bruno
npx @usebruno/cli run rest/11-deploy --env pre-prod
```

## `rest/11-deploy` — deploy key verification (AP-446)

Guards the endpoint the Deploy connect wizard calls,
`POST /api/projects/{id}/deploy/provider/verify`. It probes a **real** Railway
key against the **real** Railway API, which is the only way this suite could
have caught the production bug it exists for: Railway sits behind Cloudflare,
which rejected our default `Python-urllib/3.x` User-Agent with
`HTTP 403 error code: 1010` — so every key, valid or not, came back "invalid".
A mocked test cannot see that. This one can.

The suite is probe-only (nothing is stored) and cleans up the project it makes,
so it is safe to run against pre-prod.
