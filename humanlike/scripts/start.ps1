<#
.SYNOPSIS
Per-session ordered startup: Ollama -> sidecar (M2) -> game server (optional).
.EXAMPLE
powershell -ExecutionPolicy Bypass -File start.ps1
.EXAMPLE
powershell -ExecutionPolicy Bypass -File start.ps1 -Server
#>

# DEPRECATED (2026-07-21): the native-Windows flow is no longer maintained.
# Use the Docker runtime instead: humanlike/docker/README.md
# (Known issue left as-is: this flow put the sidecar on port 8085, which
# collides with mangosd's world port.)

[CmdletBinding()]
param(
    [switch]$Server,
    [ValidateSet("M1", "M2", "Auto")]
    [string]$Milestone = "Auto"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$RepoRoot   = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$SidecarDir = Join-Path $RepoRoot "sidecar"

if ($Milestone -eq "Auto") {
    if (Test-Path (Join-Path $SidecarDir ".venv\Scripts\uvicorn.exe")) { $Milestone = "M2" } else { $Milestone = "M1" }
    Write-Status "info" "Milestone auto-detected: $Milestone"
}

# --- 1. Ollama ---------------------------------------------------------------
if (Test-Http "http://127.0.0.1:11434/api/tags") {
    Write-Status "ok" "Ollama is up"
} else {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Status "FAILED" "ollama not on PATH - run setup.ps1 first"
        exit 1
    }
    Write-Status ".." "Starting Ollama"
    Start-Process ollama -ArgumentList "serve" -WindowStyle Minimized
    $up = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Http "http://127.0.0.1:11434/api/tags") { $up = $true; break }
    }
    if (-not $up) {
        Write-Status "FAILED" "Ollama did not answer on 127.0.0.1:11434 within 30s. Run 'ollama serve' manually to see the error."
        exit 1
    }
    Write-Status "ok" "Ollama started"
}

# --- 2. Sidecar (M2) ---------------------------------------------------------
if ($Milestone -eq "M2") {
    if (Test-Http "http://127.0.0.1:8085/docs") {
        Write-Status "ok" "Sidecar already running"
    } else {
        $uvicorn = Join-Path $SidecarDir ".venv\Scripts\uvicorn.exe"
        if (-not (Test-Path $uvicorn)) {
            Write-Status "FAILED" "$uvicorn not found - run setup.ps1 -Milestone M2 first"
            exit 1
        }
        Write-Status ".." "Starting brain sidecar on port 8085"
        Start-Process $uvicorn -ArgumentList "--factory", "brain.server:create_app", "--host", "127.0.0.1", "--port", "8085" -WorkingDirectory $SidecarDir
        $up = $false
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 1
            if (Test-Http "http://127.0.0.1:8085/docs") { $up = $true; break }
        }
        if (-not $up) {
            Write-Status "FAILED" "Sidecar did not answer on 127.0.0.1:8085 within 15s - check the uvicorn window for the error."
            exit 1
        }
        Write-Status "ok" "Sidecar started"
    }
} else {
    Write-Status "skipped" "M1 mode - no sidecar"
}

# --- 3. Game server (optional) ----------------------------------------------
if ($Server) {
    $settings = Get-Settings
    if (-not $settings.serverDir) {
        Write-Status "FAILED" "No server directory saved - run setup.ps1 first"
        exit 1
    }
    foreach ($exe in @("realmd.exe", "mangosd.exe")) {
        $procName = [System.IO.Path]::GetFileNameWithoutExtension($exe)
        if (Get-Process -Name $procName -ErrorAction SilentlyContinue) {
            Write-Status "ok" "$exe already running - skipped"
            continue
        }
        $exePath = Join-Path $settings.serverDir $exe
        if (Test-Path $exePath) {
            Start-Process $exePath -WorkingDirectory $settings.serverDir
            Write-Status "ok" "Started $exe"
        } else {
            Write-Status "warn" "$exe not found in $($settings.serverDir) - skipped"
        }
    }
}

Write-Host ""
Write-Status "ok" "Startup sequence complete"
