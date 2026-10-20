# Connected apps

Agentira can list other apps in the top-bar **app switcher** (the grid button left of the logo). An app keeps its own data and
schema; it shares only **login**, the **selected project**, and API credentials.

## Configure

Build-time, no runtime request: set `VITE_CONNECTED_APPS` for the frontend build (empty or invalid hides the switcher). With docker compose it is forwarded as a build arg, so put it in the environment or `.env` used for `docker compose up --build frontend`; changing it needs a frontend rebuild, not just a restart.

```bash
VITE_CONNECTED_APPS='[{"key":"ezine","name":"Ezine","description":"Design, mockups & prototypes","url":"http://localhost:4400"}]'
```

### Railway

The frontend service builds from `frontend/Dockerfile` (Root Directory `frontend`). Railway passes service variables to Docker builds as build args for every `ARG` the Dockerfile declares, so set `VITE_CONNECTED_APPS` as a variable on the **frontend** service and redeploy (a variable change triggers a rebuild). Use the connected app's public **HTTPS** URL: a form POST from an HTTPS page to an `http://` URL is blocked or warned by browsers. Leave it unset to keep the switcher hidden. The compose build arg is only for local compose; Railway does not read it.

## What an app must do

1. **Handoff.** The switcher form-POSTs `token` (the user's Agentira JWT) and `project` (current project id) to `<url>/auth/handoff`.
   A form POST keeps the token out of URLs, history and Referer. The app must:
   - require the request `Origin` to be this Agentira (blocks login-CSRF);
   - validate the token with `GET /api/profiles/me` (a JWT or any Agentira API key works);
   - mint its own session and redirect into itself (e.g. `/?project=<id>`).
2. **API / MCP auth.** Accept the same Agentira API key as `Authorization: Bearer`, validated via `/api/profiles/me`.
3. **Projects.** List projects with `GET /api/projects` using the caller's token; scope app data to project membership.

Reference implementation: Ezine (`agentira-auth.mjs`, `POST /auth/handoff`).
