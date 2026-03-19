$ErrorActionPreference = "Stop"

Write-Host "🦞 Testing Agentira integration with OpenClaw" -ForegroundColor Cyan

# 1. Verify skills are loaded
Write-Host "`n[1/3] Checking if OpenClaw sees Agentira skills..." -ForegroundColor Yellow
$skills = openclaw skills list 2>&1
if ($skills -match "agentira" -or $skills -match "mcporter") {
    Write-Host "✅ Skills found (mcporter and/or agentira)" -ForegroundColor Green
} else {
    Write-Host "❌ Skills not loaded in OpenClaw" -ForegroundColor Red
    exit 1
}

# 2. Test MCPorter native tool calling
Write-Host "`n[2/3] Testing mcporter call directly to Agentira MCP (via stdio)..." -ForegroundColor Yellow
$mcpOutput = mcporter list agentira --config "c:\Users\ali_f\.openclaw\mcporter.json" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ mcporter call failed" -ForegroundColor Red
    Write-Host $mcpOutput -ForegroundColor DarkGray
    exit 1
} else {
    Write-Host "✅ mcporter successfully loaded tools via stdio" -ForegroundColor Green
    Write-Host $mcpOutput -ForegroundColor DarkGray
}
# 3. Test Agentira REST API health
Write-Host "`n[3/3] Testing Agentira REST API base..." -ForegroundColor Yellow
$restStatus = Invoke-RestMethod -Uri "http://127.0.0.1:8111/api/projects" -Method Get -ErrorAction SilentlyContinue
if ($?) {
    Write-Host "✅ Agentira REST API is accessible directly" -ForegroundColor Green
} else {
    Write-Host "❌ Agentira REST API unreachable" -ForegroundColor Red
    exit 1
}

Write-Host "`n🎉 All tests passed! OpenClaw is ready to manage Agentira tasks." -ForegroundColor Cyan
