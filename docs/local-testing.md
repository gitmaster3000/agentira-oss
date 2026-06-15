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

Use the **`--test`** flag — it puts the daemon in its own isolated home
(`~/.agentira-test`) so it never collides with your prod daemon. It reads the
backend connection from your environment (it does **not** hardcode a URL or
key); set those two vars once, then drive it with `--test`:

```bash
export AGENTIRA_DAEMON_API_URL=http://localhost:8111
export AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only   # = AGENTIRA_DEV_API_KEY on the backend

agentira daemon --test start
agentira daemon --test status     # Home ~/.agentira-test · Backend http://localhost:8111
agentira daemon --test logs -n 20
```

Expect `Registered 3 runtime(s)` in the logs. If you run `--test start`
without those two vars set, it stops and tells you exactly what to export — no
silent wrong-backend.

Prefer to not export globally? Wrap them in an alias:

```bash
alias agentira-test='AGENTIRA_DAEMON_API_URL=http://localhost:8111 \
  AGENTIRA_DAEMON_API_KEY=dev-daemon-key-local-only agentira daemon --test'
# then:  agentira-test start  ·  agentira-test status  ·  agentira-test stop
```

### Managing the two daemons

| Command | Acts on |
|---|---|
| `agentira daemon <cmd>` | your **prod** daemon (`~/.agentira`) |
| `agentira daemon --test <cmd>` | the **test** daemon (`~/.agentira-test`) |

`<cmd>` = `start` · `stop` · `restart` · `status` · `logs`. Independent
processes — stopping one never touches the other, and every command prints its
**Home + Backend** so you always know which is which.

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
agentira daemon --test stop   # stops ONLY the test daemon
```

Your prod daemon (default `~/.agentira`) is never touched — different state dir,
different backend. Wipe local data with `docker compose down -v` and re-seed.

---

## How it's wired (config, not code)

| Concern | Solution |
|---|---|
| Don't touch prod data | Local Postgres + a sandbox `preview` org |
| Google OAuth can't do localhost | Seeded **password** test user (`preview`) |
| Daemon already runs prod | Second daemon via `--test` (`AGENTIRA_HOME=~/.agentira-test`) |
| Browser login fiddly locally | Dev static-key bypass, gated by **`AGENTIRA_ENV=dev`** |
| Dev vs prod must be portable | `AGENTIRA_ENV` config (default `prod`) — no host sniffing |
| Catch Postgres-specific bugs | Local runs Postgres, same engine as prod |
