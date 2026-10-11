<#
.SYNOPSIS
  One-command local start for the MTF research app.

.DESCRIPTION
  1. Verifies Docker Desktop is reachable (launches it if installed but not running)
  2. docker compose up -d  (idempotent: running containers are reused, never recreated)
  3. Waits for PostgreSQL and Redis health checks
  4. Waits for FastAPI /api/health
  5. Starts the Vite frontend in its own window unless it is already serving
  6. Waits for the frontend
  7. Checks /api/fyers/status?verify=true (one server-cached FYERS call at most)
  8. Opens the frontend in the default browser

  Never deletes containers/volumes, never force-recreates, never logs in to
  FYERS for you. If FYERS needs a login, the app shows a "Connect FYERS" button.

.EXAMPLE
  .\start-mtf.ps1
  .\start-mtf.ps1 -NoBrowser
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$ComposeFile = Join-Path $Backend 'docker-compose.yml'
$ApiBase = 'http://127.0.0.1:8000/api'
$FrontendPort = if ($env:PORT) { [int]$env:PORT } else { 8443 }
$FrontendUrl = "http://localhost:$FrontendPort/"

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "    OK  $Message" -ForegroundColor Green }
function Write-Warn2([string]$Message) { Write-Host "    !!  $Message" -ForegroundColor Yellow }
function Fail([string]$Message) { Write-Host "    XX  $Message" -ForegroundColor Red; exit 1 }

function Test-DockerReachable {
    & docker info --format '{{.ServerVersion}}' *> $null
    return ($LASTEXITCODE -eq 0)
}

function Find-DockerDesktopExe {
    $candidates = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe"
    )
    $dockerCli = Get-Command docker -ErrorAction SilentlyContinue
    if ($dockerCli) {
        # <install>\resources\bin\docker.exe -> <install>\Docker Desktop.exe
        $candidates += Join-Path (Split-Path (Split-Path (Split-Path $dockerCli.Source))) 'Docker Desktop.exe'
    }
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

function Wait-Until([string]$What, [scriptblock]$Condition, [int]$Seconds = $TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) { return $true }
        Start-Sleep -Seconds 2
    }
    Fail "Timed out after ${Seconds}s waiting for $What"
}

function Get-ContainerHealth([string]$Service) {
    $id = (& docker compose -f $ComposeFile ps -q $Service 2>$null | Select-Object -First 1)
    if (-not $id) { return 'missing' }
    $health = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $id 2>$null)
    return "$health".Trim()
}

function Test-Http([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
    } catch [System.Net.WebException] {
        # Any HTTP response (even 4xx/5xx) means the server is up.
        return ($null -ne $_.Exception.Response)
    } catch {
        return $false
    }
}

# ---- 1. Docker ---------------------------------------------------------------
Write-Step 'Checking Docker Desktop'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Fail 'docker CLI not found on PATH. Install Docker Desktop.' }
if (-not (Test-DockerReachable)) {
    $exe = Find-DockerDesktopExe
    if (-not $exe) { Fail 'Docker engine is not reachable and Docker Desktop.exe was not found. Start Docker Desktop manually.' }
    Write-Warn2 'Docker engine not reachable -- launching Docker Desktop'
    Start-Process -FilePath $exe | Out-Null
    Wait-Until 'Docker engine' { Test-DockerReachable } | Out-Null
}
Write-Ok 'Docker engine reachable'

# ---- 2. Services ---------------------------------------------------------------
Write-Step 'Starting backend services (docker compose up -d; existing containers are reused)'
& docker compose -f $ComposeFile up -d
if ($LASTEXITCODE -ne 0) { Fail 'docker compose up -d failed (see output above)' }

# ---- 3. PostgreSQL / Redis -----------------------------------------------------
foreach ($svc in 'db', 'redis') {
    Write-Step "Waiting for $svc health"
    Wait-Until "$svc to become healthy" { (Get-ContainerHealth $svc) -eq 'healthy' } | Out-Null
    Write-Ok "$svc healthy"
}

# ---- 4. FastAPI ------------------------------------------------------------------
Write-Step 'Waiting for FastAPI /api/health'
Wait-Until 'FastAPI /api/health' { Test-Http "$ApiBase/health" } | Out-Null
$health = Invoke-RestMethod -Uri "$ApiBase/health" -TimeoutSec 10
$components = ($health.components | ForEach-Object { "$($_.name)=$($_.status)" }) -join ', '
Write-Ok "API $($health.status) ($components)"

# ---- 5/6. Frontend -----------------------------------------------------------------
Write-Step "Checking frontend on $FrontendUrl"
if (Test-Http $FrontendUrl) {
    Write-Ok 'Frontend already running -- not starting another'
} else {
    if (-not (Test-Path (Join-Path $Root 'node_modules'))) { Fail "node_modules missing. Run 'npm install' in $Root once, then re-run." }
    Write-Warn2 'Frontend not running -- starting Vite in a separate window'
    Start-Process -FilePath 'powershell.exe' -WorkingDirectory $Root -WindowStyle Minimized `
        -ArgumentList '-NoExit', '-NoProfile', '-Command', "`$Host.UI.RawUI.WindowTitle = 'MTF frontend (Vite)'; npm run dev" | Out-Null
    Wait-Until 'Vite frontend' { Test-Http $FrontendUrl } 120 | Out-Null
    Write-Ok 'Frontend started'
}

# ---- 7. FYERS ---------------------------------------------------------------------
Write-Step 'Checking FYERS session'
$fyersState = 'UNKNOWN'
try {
    $fyers = Invoke-RestMethod -Uri "$ApiBase/fyers/status?verify=true" -TimeoutSec 30
    $fyersState = $fyers.status
    switch ($fyers.status) {
        'CONNECTED' {
            $v = if ($fyers.verified) { 'verified with FYERS' } else { "not verified: $($fyers.verification_error)" }
            Write-Ok "FYERS CONNECTED ($v; expires $($fyers.access_expires_at))"
        }
        'MOCK' { Write-Warn2 'FYERS in MOCK mode (USE_MOCK_FYERS=true) -- no live data' }
        'REFRESH_REQUIRED' {
            Write-Warn2 'FYERS session expired. Reconnect with your PIN in the app, or log in:'
            Write-Host "        $ApiBase/fyers/login"
        }
        'LOGIN_REQUIRED' {
            Write-Warn2 'FYERS login required. Use "Connect FYERS" in the app, or open:'
            Write-Host "        $ApiBase/fyers/login"
        }
        default { Write-Warn2 "FYERS status $($fyers.status): $($fyers.message)" }
    }
} catch {
    Write-Warn2 "Could not read /api/fyers/status: $($_.Exception.Message)"
}

# ---- 8. Browser -------------------------------------------------------------------
if (-not $NoBrowser) {
    Write-Step "Opening $FrontendUrl"
    Start-Process $FrontendUrl | Out-Null
}

Write-Host ''
Write-Host "MTF is up. Frontend: $FrontendUrl  API: $ApiBase  FYERS: $fyersState" -ForegroundColor Green
