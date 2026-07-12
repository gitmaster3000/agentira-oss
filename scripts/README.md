# `scripts/` — operational scripts

| Script | What it does | Run as |
|---|---|---|
| `bootstrap_db.py` | Called inside the backend container at startup. Runs `services.bootstrap()` → tables + migrations + default seeds. | python (auto, in container) |
| `write_cli_manifest.py` | Writes `backend/static/cli/manifest.json` from the baked CLI wheel (Docker build). | python (auto, in container) |
| `install-daemon.sh` | Mac / Linux daemon installer. Checks prereqs, pip-installs from instance wheel, writes `~/.agentira/.env`. | `bash` (on a user's machine) |
| `install-daemon.ps1` | Windows daemon installer. Same shape as `install-daemon.sh`. | PowerShell (on a user's machine) |

## Sharing the installers

Customers install from **their Agentira instance URL** (served by the backend image):

**Mac / Linux:**
```bash
curl -fsSL https://YOUR-INSTANCE.up.railway.app/api/public/install.sh | bash
```

**Windows (PowerShell as Administrator):**
```powershell
iwr -useb https://YOUR-INSTANCE.up.railway.app/api/public/install.ps1 | iex
```

The CLI wheel is baked into the backend Docker image on every Railway deploy.
Customers never need GitHub access.

To skip interactive prompts, put values in `~/.agentira/.env` before piping, or
export them only for that one command:

```bash
AGENTIRA_DAEMON_API_URL=https://your.url \
AGENTIRA_DAEMON_API_KEY=hex-from-settings \
bash <(curl -fsSL https://your.url/api/public/install.sh)
```

## Re-running on a previously-configured machine

Both installers back up an existing `~/.agentira/.env` to `.env.bak.<timestamp>` before writing a new one. You can re-run safely after rotating an API key or changing the backend URL.