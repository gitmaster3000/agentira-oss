# `scripts/` — operational scripts

| Script | What it does | Run as |
|---|---|---|
| `bootstrap_db.py` | Called inside the backend container at startup. Runs `services.bootstrap()` → tables + migrations + default seeds. | python (auto, in container) |
| `install-daemon.sh` | Mac / Linux daemon installer. Checks prereqs, pip-installs `agentira-cli`, writes `~/.agentira/.env`. | `bash` (on a user's machine) |
| `install-daemon.ps1` | Windows daemon installer. Same shape as `install-daemon.sh`. | PowerShell (on a user's machine) |

## Sharing the installers

Once this is merged to `main`, users can install with a one-liner:

**Mac / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/gitmaster3000/agentira/main/scripts/install-daemon.sh | bash
```

**Windows (PowerShell as Administrator):**
```powershell
iwr -useb https://raw.githubusercontent.com/gitmaster3000/agentira/main/scripts/install-daemon.ps1 | iex
```

To skip the interactive prompts, set the env vars before piping:

```bash
AGENTIRA_DAEMON_API_URL=https://your.url \
AGENTIRA_DAEMON_API_KEY=hex-from-settings \
bash <(curl -fsSL https://.../install-daemon.sh)
```

## Re-running on a previously-configured machine

Both installers back up an existing `~/.agentira/.env` to `.env.bak.<timestamp>` before writing a new one. You can re-run safely after rotating an API key or changing the backend URL.
