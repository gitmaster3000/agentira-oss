# Agentira daemon installer — Windows.
#
# Pipeable: iwr -useb https://.../install-daemon.ps1 | iex
#
# What it does:
#   1. Checks for python (>=3.11), claude CLI, git
#   2. pip-installs agentira-cli from this GitHub repo
#   3. Creates $env:USERPROFILE\.agentira\.env and prompts for backend URL + API key
#   4. Prints the command to start the daemon
#
# Env vars it respects (skip interactive prompts):
#   AGENTIRA_DAEMON_API_URL  — backend URL (e.g. https://x.railway.app)
#   AGENTIRA_DAEMON_API_KEY  — your workspace API key
#   AGENTIRA_REPO            — defaults to gitmaster3000/agentira

$ErrorActionPreference = 'Stop'

function Write-Step($msg)  { Write-Host "▸ " -ForegroundColor Cyan -NoNewline; Write-Host $msg -ForegroundColor White }
function Write-Ok($msg)    { Write-Host "  ✓ " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn($msg)  { Write-Host "  ! " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Fail($msg)  { Write-Host "  ✗ " -ForegroundColor Red -NoNewline; Write-Host $msg; exit 1 }
function Write-Hint($msg)  { Write-Host "    $msg" -ForegroundColor DarkGray }

Write-Host ""
Write-Host "Agentira daemon installer" -ForegroundColor White
Write-Host "Windows · ~3 minutes" -ForegroundColor DarkGray
Write-Host ""

# ── Step 1: prerequisites ───────────────────────────────────────────────
Write-Step "Checking prerequisites"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Fail "Python not found.
    Install Python 3.11+ from https://www.python.org/downloads/
    (Make sure 'Add to PATH' is checked.)"
}

$pyVerRaw = & $python.Source --version 2>&1
if ($pyVerRaw -match 'Python (\d+)\.(\d+)') {
    $pyMajor = [int]$Matches[1]; $pyMinor = [int]$Matches[2]
    if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 11)) {
        Write-Fail "Python $pyMajor.$pyMinor found, but 3.11+ required.
    Install a newer Python from https://www.python.org/downloads/"
    }
    Write-Ok "Python $pyMajor.$pyMinor"
} else {
    Write-Fail "Could not parse python version: $pyVerRaw"
}

$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Warn "claude CLI not found on PATH."
    Write-Hint "Install with: npm install -g @anthropic-ai/claude-code"
    Write-Hint "(Or follow instructions at https://github.com/anthropics/claude-code)"
    Write-Hint ""
    Write-Hint "The daemon will still install, but won't have a runtime"
    Write-Hint "to dispatch to until you install claude."
    $resp = Read-Host "    Continue anyway? [y/N]"
    if ($resp -notmatch '^[Yy]') {
        Write-Fail "Install claude first, then re-run."
    }
} else {
    $claudeVer = (& claude --version 2>&1 | Select-Object -First 1)
    Write-Ok "Claude CLI: $claudeVer"
}

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) {
    Write-Fail "git not found. Install from https://git-scm.com/downloads"
}
Write-Ok "git $((& git --version) -replace 'git version ', '')"

# ── Step 2: pip install ─────────────────────────────────────────────────
Write-Step "Installing agentira-cli"

$repo = if ($env:AGENTIRA_REPO) { $env:AGENTIRA_REPO } else { "gitmaster3000/agentira" }
$pipTarget = "git+https://github.com/$repo.git#subdirectory=agentira-cli"

# Prefer --user when not in a venv.
$pipArgs = @("install", "--upgrade", "--quiet", $pipTarget)
if (-not $env:VIRTUAL_ENV) {
    $pipArgs = @("install", "--upgrade", "--quiet", "--user", $pipTarget)
}

try {
    & $python.Source -m pip @pipArgs
    if ($LASTEXITCODE -ne 0) { throw "pip exit code $LASTEXITCODE" }
    Write-Ok "agentira-cli installed from $repo"
} catch {
    Write-Fail "pip install failed: $_
    Try manually: python -m pip install --user '$pipTarget'"
}

# Verify the entry point landed somewhere on PATH.
$agentira = Get-Command agentira -ErrorAction SilentlyContinue
if (-not $agentira) {
    Write-Warn "'agentira' command not on PATH after install."
    Write-Hint "If you used --user, add Python's user-scripts dir to PATH."
    Write-Hint "Find it with: python -m site --user-base"
    Write-Hint "Then add <that-path>\Scripts to your PATH env var."
    Write-Hint "Open a new terminal and re-run."
    exit 1
}
Write-Ok "agentira CLI on PATH: $($agentira.Source)"

# ── Step 3: config ──────────────────────────────────────────────────────
Write-Step "Configuring connection"

$configDir = Join-Path $env:USERPROFILE ".agentira"
$envFile = Join-Path $configDir ".env"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

$apiUrl = $env:AGENTIRA_DAEMON_API_URL
if (-not $apiUrl) {
    Write-Host ""
    Write-Host "  Backend URL" -ForegroundColor White
    Write-Host "  The URL of the Agentira instance you signed up at." -ForegroundColor DarkGray
    Write-Host "  Example: https://agentira.up.railway.app" -ForegroundColor DarkGray
    $apiUrl = Read-Host "  →"
    if (-not $apiUrl) {
        Write-Fail "Backend URL required. Re-run when ready."
    }
}
$apiUrl = $apiUrl.TrimEnd('/')

$apiKey = $env:AGENTIRA_DAEMON_API_KEY
if (-not $apiKey) {
    Write-Host ""
    Write-Host "  API key" -ForegroundColor White
    Write-Host "  From the website → top-right avatar → Settings → API key." -ForegroundColor DarkGray
    Write-Host "  Click Reveal, then copy the hex string." -ForegroundColor DarkGray
    $apiKeySecure = Read-Host "  →" -AsSecureString
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($apiKeySecure))
    if (-not $apiKey) {
        Write-Fail "API key required. Re-run when ready."
    }
}

# Back up existing config if any.
if (Test-Path $envFile) {
    $backup = "${envFile}.bak.$([int][double]::Parse((Get-Date -UFormat %s)))"
    Copy-Item $envFile $backup
    Write-Warn "Existing config backed up to $backup"
}

@"
# Agentira daemon configuration.
# Generated $(Get-Date) by install-daemon.ps1
#
# Edit any of these and restart the daemon to pick them up.

AGENTIRA_DAEMON_API_URL=$apiUrl
AGENTIRA_DAEMON_API_KEY=$apiKey
"@ | Set-Content -Path $envFile -Encoding UTF8

# Restrict ACL — current user only.
$acl = Get-Acl $envFile
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "$env:USERNAME", "FullControl", "Allow")
$acl.SetAccessRule($rule)
Set-Acl -Path $envFile -AclObject $acl

Write-Ok "Config written to $envFile (current-user ACL)"

# ── Step 4: smoke ──────────────────────────────────────────────────────
Write-Step "Smoke-checking the backend"

try {
    $r = Invoke-WebRequest -Uri "$apiUrl/api/statuses" -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
    Write-Ok "Backend reachable: $apiUrl"
} catch {
    Write-Warn "Could not reach $apiUrl/api/statuses"
    Write-Hint "Double-check the URL. If correct, the operator may still be"
    Write-Hint "provisioning the service — try again in a minute."
}

# ── Done ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "✓ Installed." -ForegroundColor Green
Write-Host ""
Write-Host "Start the daemon:" -ForegroundColor White
Write-Host "  agentira daemon" -ForegroundColor Cyan
Write-Host ""
Write-Host "Keep it running across reboots:" -ForegroundColor White
Write-Host "  agentira daemon install-service" -ForegroundColor Cyan
Write-Host "  (creates a Windows scheduled task; auto-starts at login)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Need help?" -ForegroundColor White
Write-Host "  • First-time guide: https://github.com/$repo/blob/main/docs/first-user.md" -ForegroundColor Cyan
Write-Host "  • Troubleshooting: same doc, 'Troubleshooting' section" -ForegroundColor DarkGray
Write-Host ""
