# Testing Agentira locally

Run the whole product on your machine — backend + MCP + Postgres + a daemon —
against **seeded mock data**, isolated from prod. No cloud, no Google OAuth.

Docker runs the local stack; the `agentira` CLI runs the daemon (which spawns
the real runtimes — claude/openclaw/etc. — on your host).

---

## 1. Bring up the local stack (Postgres, prod parity)

```bash
cd agentira
docker compose up -d            # backend :8111, mcp :8000, frontend :3111, postgres
```

Local runs on **Postgres** (same engine as prod). First boot creates a fresh DB
and `bootstrap_db.py` seeds defaults.

> Changed deps recently? `docker compose build backend mcp` first.

## 2. Seed mock data + a test user

```bash
docker exec agentira-backend-1 python scripts/seed_test_data.py
```

Creates a sandbox **`preview` org**, two demo projects (epics + tasks across
every board status), the default agent team, and a login:

```
preview / preview1234
```

Open **http://localhost:3111** and sign in (username/password — no Google OAuth
on localhost).

## 3. Run a TEST daemon against local

A daemon talks to **one** backend. Your prod daemon points at prod, so you run a
*second* daemon pointed at local. `AGENTIRA_HOME` gives it its own state, so it
runs **alongside** the prod daemon without colliding on pid/creds/logs.

### Easiest: the dev-key bypass

Dev/prod is a **config switch**, not host-detection code. The local backend
sets `AGENTIRA_ENV=dev` + an `AGENTIRA_DEV_API_KEY` (see
`docker-compose.override.yml`). A daemon presenting that key authenticates as
the `preview` profile — no browser login:

**First, turn on developer mode** — the whole test/prod split is dev-only and
hidden from customers (a shipped CLI has no `--test`/`--prod` and acts only on
the one configured daemon). Set this once in your shell profile:

```bash
export AGENTIRA_DEV_MODE=1
```

> `AGENTIRA_DEV_MODE` only changes local CLI ergonomics — it is **not** a
> security boundary. The real gate is server-side (`AGENTIRA_ENV=dev` +
> `AGENTIRA_DEV_API_KEY` on the backend), which prod never sets, so a daemon
> can't reach prod even with this flag on.

With dev mode on, **test is the default.** A bare `agentira daemon ...` targets
an isolated test daemon (`~/.agentira-test`) — it can never touch prod by
accident. Point it at your local stack with the **dev-scoped** vars (safe to
keep permanently in your profile — they only feed the test daemon and never
retarget prod):

```bash
export AGENTIRA_TEST_API_URL=http://localhost:8111
export AGENTIRA_TEST_API_KEY=dev-daemon-key-local-only   # = AGENTIRA_DEV_API_KEY on the backend

agentira daemon start             # test by default (dev mode)
agentira daemon status            # Home ~/.agentira-test · Backend http://localhost:8111
agentira daemon logs -n 20
```

Expect `Registered 3 runtime(s)` in the logs. If you run `start` without those
two vars set, it stops and tells you exactly what to export — no silent
wrong-backend. (`--test` is accepted too, as the explicit form of the default.)

> **Why `AGENTIRA_TEST_*` and not `AGENTIRA_DAEMON_*`?** `DaemonConfig` reads
> `AGENTIRA_DAEMON_API_URL` for *every* daemon, so exporting that would also
> retarget your prod daemon. The `AGENTIRA_TEST_*` vars are mapped onto
> `AGENTIRA_DAEMON_*` only inside the test re-exec, so `--prod` always stays on
> its real backend.

### Managing the two daemons

| Command | Acts on |
|---|---|
| `agentira daemon <cmd>` *(or `--test`)* | the **test** daemon (`~/.agentira-test`) — **default** |
| `agentira daemon --prod <cmd>` | your real **prod** daemon (`~/.agentira`) — explicit |

`<cmd>` = `start` · `stop` · `restart` · `status` · `logs`. Both are independent
processes (stopping one never touches the other), and every command prints its
**Home + Backend** so you always know which is which.

**Prod is guarded.** Acting on prod requires the explicit `--prod` flag, and the
state-changing commands (`start` / `stop` / `restart`) show what they're about
to do and ask you to confirm first:

```text
⚠  PROD daemon — about to run a state-changing command.
  Command:  daemon restart
  Home:     ~/.agentira
  Backend:  https://flowty-api-production.up.railway.app
  Currently: running (PID 72527)
Proceed against PROD? [y/N]:
```

`--prod status` / `--prod logs` are read-only and don't prompt.

> **Why it's safe:** the bypass is honored only when `AGENTIRA_ENV=dev`. The
> code default is `prod`, so it's fail-safe OFF on Railway / AWS / GCP / any
> host unless a dev config explicitly opts in — no provider-specific code.
> Prod configs never set `AGENTIRA_ENV=dev` or `AGENTIRA_DEV_API_KEY`.

### Alternative: normal browser login

Works like prod once the backend advertises a frontend URL — set
`FRONTEND_URL=http://localhost:3111` on the backend, then:

```bash
AGENTIRA_HOME=~/.agentira-test \
  agentira daemon login --api-url http://localhost:8111   # opens localhost:3111, log in preview/preview1234
AGENTIRA_HOME=~/.agentira-test agentira daemon start
```

## 4. Exercise the loop

In the local UI (as `preview`): open a demo task, hand it to an agent, and watch
the **test daemon** pick it up and run it on your host. Follow
`~/.agentira-test/daemon.log`.

## 5. Stop / switch back

```bash
agentira daemon stop          # stops the test daemon (the default)
```

Your prod daemon is never touched — different state dir, different backend, and
it's reachable only via the explicit, confirmed `--prod`. Wipe local data with
`docker compose down -v` and re-seed.

---

## How it's wired (config, not code)

| Concern | Solution |
|---|---|
| Don't touch prod data | Local Postgres + a sandbox `preview` org |
| Google OAuth can't do localhost | Seeded **password** test user (`preview`) |
| Daemon already runs prod | Test is the **default** (`~/.agentira-test`); prod needs explicit, confirmed `--prod` |
| Browser login fiddly locally | Dev static-key bypass, gated by **`AGENTIRA_ENV=dev`** |
| Dev vs prod must be portable | `AGENTIRA_ENV` config (default `prod`) — no host sniffing |
| Catch Postgres-specific bugs | Local runs Postgres, same engine as prod |
