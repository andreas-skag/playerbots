<#
.SYNOPSIS
One-time (re-runnable) setup for the human-like LLM bots.
.DESCRIPTION
Installs Ollama, pulls models, prepares the sidecar (M2), patches
aiplayerbot.conf and deploys character cards. Idempotent: safe to re-run;
every step reports [done]/[skipped]/[FAILED].
.EXAMPLE
powershell -ExecutionPolicy Bypass -File setup.ps1
.EXAMPLE
powershell -ExecutionPolicy Bypass -File setup.ps1 -Milestone M2
#>
[CmdletBinding()]
param(
    [ValidateSet("M1", "M2")]
    [string]$Milestone = "M1",
    [string]$ServerDir
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$RepoRoot     = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$HumanlikeDir = Join-Path $RepoRoot "humanlike"
$SidecarDir   = Join-Path $RepoRoot "sidecar"

$settings = Get-Settings

# --- 1. Ollama ---------------------------------------------------------------
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Status "skipped" "Ollama already installed"
} else {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Status "FAILED" "winget not found. Install Ollama manually from https://ollama.com/download/windows and re-run."
        exit 1
    }
    Write-Status "..." "Installing Ollama via winget"
    winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Status "FAILED" "winget install Ollama.Ollama failed (exit $LASTEXITCODE)"
        exit 1
    }
    # pick up the PATH the installer just wrote
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Status "FAILED" "Ollama installed but not on PATH yet. Open a new terminal and re-run setup.ps1."
        exit 1
    }
    Write-Status "done" "Ollama installed"
}

# --- 2. Models ---------------------------------------------------------------
$models = @($settings.chatModel)
if ($Milestone -eq "M2") { $models += $settings.utilityModel }
foreach ($model in $models) {
    Write-Status "..." "Pulling model $model (fast if already present)"
    ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        Write-Status "FAILED" "ollama pull $model failed. Is the Ollama service running? Try 'ollama serve' in another window."
        exit 1
    }
    Write-Status "done" "Model $model available"
}

# --- 3. Sidecar (M2 only) ----------------------------------------------------
if ($Milestone -eq "M2") {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Status "FAILED" "python not found. Install Python 3.11+ from https://www.python.org/downloads/ and re-run."
        exit 1
    }
    $pyVersion = $null
    try {
        $pyVersion = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        $pyVersion = $null
    }
    if ($pyVersion) { $pyVersion = "$pyVersion".Trim() }
    if (-not $pyVersion -or $pyVersion -notmatch '^\d+\.\d+$') {
        Write-Status "FAILED" "python did not run (Windows Store alias?). Install Python 3.11+ from https://www.python.org/downloads/ and re-run."
        exit 1
    }
    $pyParts = $pyVersion.Split('.')
    if ([int]$pyParts[0] -lt 3 -or ([int]$pyParts[0] -eq 3 -and [int]$pyParts[1] -lt 11)) {
        Write-Status "FAILED" "Python 3.11+ required, found $pyVersion"
        exit 1
    }
    $venvPython = Join-Path $SidecarDir ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        Write-Status "skipped" "Sidecar venv exists"
    } else {
        Write-Status "..." "Creating sidecar venv"
        & python -m venv (Join-Path $SidecarDir ".venv")
        if ($LASTEXITCODE -ne 0) { Write-Status "FAILED" "venv creation failed"; exit 1 }
        Write-Status "done" "Sidecar venv created"
    }
    Write-Status "..." "Installing sidecar package"
    & $venvPython -m pip install --quiet -e $SidecarDir
    if ($LASTEXITCODE -ne 0) { Write-Status "FAILED" "pip install failed - see output above"; exit 1 }
    Write-Status "done" "Sidecar installed"

    $configToml = Join-Path $SidecarDir "config.toml"
    if (Test-Path $configToml) {
        Write-Status "skipped" "sidecar\config.toml exists"
    } else {
        Copy-Item (Join-Path $SidecarDir "config.example.toml") $configToml
        Write-Status "done" "sidecar\config.toml created from example"
    }
}

# --- 4. Server directory -----------------------------------------------------
if (-not $ServerDir) { $ServerDir = $settings.serverDir }
while (-not $ServerDir) {
    $ServerDir = Read-Host "Path to your server directory (the folder containing mangosd.exe)"
}
if (-not (Test-Path (Join-Path $ServerDir "mangosd.exe")) -and
    -not (Test-Path (Join-Path $ServerDir "aiplayerbot.conf"))) {
    Write-Status "warn" "Neither mangosd.exe nor aiplayerbot.conf found in $ServerDir"
    $answer = Read-Host "Continue anyway? (y/N)"
    if ($answer -ne "y") { exit 1 }
}
$settings.serverDir = "$ServerDir"
Save-Settings $settings
Write-Status "done" "Server directory saved: $ServerDir"

# --- 5. Patch aiplayerbot.conf ----------------------------------------------
$confPath = Join-Path $ServerDir "aiplayerbot.conf"
if (-not (Test-Path $confPath)) {
    Write-Status "FAILED" "aiplayerbot.conf not found in $ServerDir. Copy the dist file there first (aiplayerbot.conf.dist -> aiplayerbot.conf), then re-run."
    exit 1
}

$blockLines = Get-Content (Join-Path $HumanlikeDir "conf\m1-ollama-direct.conf.example") -Encoding UTF8
if ($Milestone -eq "M2") {
    $m2Lines  = Get-Content (Join-Path $HumanlikeDir "conf\m2-sidecar.conf.example") -Encoding UTF8
    $endpoint = @($m2Lines | Where-Object { $_ -match '^AiPlayerbot\.LLMApiEndpoint\s*=' })[0]
    $apiJson  = @($m2Lines | Where-Object { $_ -match '^AiPlayerbot\.LLMApiJson\s*=' })[0]
    if (-not $endpoint -or -not $apiJson) {
        Write-Status "FAILED" "Could not find LLMApiEndpoint/LLMApiJson lines in m2-sidecar.conf.example - file format changed?"
        exit 1
    }
    $blockLines = $blockLines | ForEach-Object {
        if ($_ -match '^AiPlayerbot\.LLMApiEndpoint\s*=') { $endpoint }
        elseif ($_ -match '^AiPlayerbot\.LLMApiJson\s*=') { $apiJson }
        else { $_ }
    }
}

$backup = "$confPath.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
Copy-Item $confPath $backup
if (-not (Test-Path $backup)) { Write-Status "FAILED" "Could not write backup $backup - aborting before any change"; exit 1 }
Write-Status "done" "Backup written: $backup"

$beginMarker = "# BEGIN humanlike-llm block"
$endMarker   = "# END humanlike-llm block"
$inBlock = $false
$kept = foreach ($line in (Get-Content $confPath)) {
    if ($line -eq $beginMarker) { $inBlock = $true; continue }
    if ($line -eq $endMarker)   { $inBlock = $false; continue }
    if ($inBlock) { continue }
    if ($line -match '^\s*AiPlayerbot\.LLM') { continue }  # loose LLM lines superseded by our block
    $line
}
$patched = @($kept) + @("", $beginMarker) + @($blockLines) + @($endMarker)
Set-Content -Path $confPath -Value $patched -Encoding Default
Write-Status "done" "aiplayerbot.conf patched with the $Milestone LLM block"

# --- 6. Character cards ------------------------------------------------------
$cardSrc = Join-Path $HumanlikeDir "llm_character_card.txt"
$cardDst = Join-Path $ServerDir "llm_character_card.txt"
if ((Test-Path $cardDst) -and ((Get-Item $cardDst).LastWriteTime -gt (Get-Item $cardSrc).LastWriteTime)) {
    Write-Status "skipped" "Server card file is newer than the repo copy - keeping your edits"
} else {
    if (Test-Path $cardDst) {
        $cardBackup = "$cardDst.bak-" + (Get-Date -Format "yyyyMMdd-HHmmss")
        Copy-Item $cardDst $cardBackup
        Write-Status "done" "Card backup written: $cardBackup"
    }
    Copy-Item $cardSrc $cardDst
    Write-Status "done" "Character cards deployed to server directory"
}

# --- Summary -----------------------------------------------------------------
Write-Host ""
Write-Status "done" "Setup complete ($Milestone)."
Write-Host "Next steps:"
Write-Host "  1. Pick your companion bots:   powershell -ExecutionPolicy Bypass -File pick-bots.ps1"
Write-Host "  2. Edit their personality cards in humanlike\llm_character_card.txt, then re-run setup.ps1 to deploy"
Write-Host "  3. Start everything:           powershell -ExecutionPolicy Bypass -File start.ps1"
