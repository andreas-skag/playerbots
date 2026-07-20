# Windows Setup/Start Automation Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three PowerShell scripts (`setup.ps1`, `start.ps1`, `pick-bots.ps1`) + shared helpers that automate the target-machine setup documented in `humanlike/README.md`.

**Architecture:** Single-purpose scripts in `humanlike/scripts/`, dot-sourcing a shared `common.ps1` (status output, settings persistence, HTTP probe). A git-ignored `settings.json` carries state between runs (server dir, models, DB connection minus password). README gains "Automated setup" sections pointing at the scripts, manual steps retained below as fallback.

**Tech Stack:** Windows PowerShell 5.1-compatible scripts (target machine); pwsh 7.4.11 at `~/pwsh/pwsh` on this box for syntax validation only.

**Spec:** `docs/superpowers/specs/2026-07-20-windows-setup-scripts-design.md`

## Global Constraints

- Scripts must be **Windows PowerShell 5.1 compatible**: no `??`, no `?.`, no `ConvertFrom-Json -AsHashtable`, no ternary; `Invoke-WebRequest` always with `-UseBasicParsing`; ASCII-safe output (no emoji/box-drawing).
- **No PowerShell execution of the scripts on this box** — behavioral verification happens on the target machine. Each task's test gate is syntax validation via the parser:
  `~/pwsh/pwsh -NoProfile -Command '$errs=$null; [System.Management.Automation.Language.Parser]::ParseFile("<abs path>",[ref]$null,[ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { "syntax OK" }'`
- All work on branch `feature/humanlike-llm-bots` in `/workspace/playerbots` (repo-local git identity already configured). The branch has open PR #1 — pushing updates it.
- No passwords stored anywhere: DB password via `Read-Host -AsSecureString`, passed to mysql via `MYSQL_PWD` env var, removed afterwards.
- Destructive-op rules from the spec: conf patching writes a timestamped backup first and uses `# BEGIN humanlike-llm block` / `# END humanlike-llm block` markers for idempotent replacement; card copy never clobbers a newer server-side file; every step prints `[done]/[skipped]/[FAILED]` (or `[ok]/[..]/[warn]`) status lines; scripts exit non-zero on failure.
- The sidecar Python suite must stay green: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -q` → 37 passed (scripts don't touch Python, run once in the final task as a regression gate).

---

### Task 1: common.ps1 + settings scaffolding + gitignore

**Files:**
- Create: `humanlike/scripts/common.ps1`
- Create: `humanlike/scripts/.gitignore`

**Interfaces:**
- Produces (dot-sourced by Tasks 2–4 via `. (Join-Path $PSScriptRoot "common.ps1")`):
  - `Write-Status([string]$Tag, [string]$Message)` — prints `[tag] message`
  - `Get-Settings()` — returns `[pscustomobject]` with keys `serverDir, chatModel, utilityModel, dbHost, dbUser, dbName` (defaults `""`, `mistral-small3.2`, `qwen3:4b`, `127.0.0.1`, `root`, `classiccharacters`), merged with `settings.json` beside the scripts if present (unknown/missing keys tolerated)
  - `Save-Settings($Settings)` — writes `settings.json` beside the scripts
  - `Test-Http([string]$Url)` — `$true` if a GET succeeds within 3 s
  - `$script:SettingsPath` — resolved path of `settings.json`

- [ ] **Step 1: Write common.ps1**

```powershell
# Shared helpers for the humanlike setup scripts. Dot-source from a sibling
# script:  . (Join-Path $PSScriptRoot "common.ps1")
# Windows PowerShell 5.1 compatible.

$script:SettingsPath = Join-Path $PSScriptRoot "settings.json"

function Write-Status([string]$Tag, [string]$Message) {
    Write-Host ("[{0}] {1}" -f $Tag, $Message)
}

function Get-Settings {
    $defaults = @{
        serverDir    = ""
        chatModel    = "mistral-small3.2"
        utilityModel = "qwen3:4b"
        dbHost       = "127.0.0.1"
        dbUser       = "root"
        dbName       = "classiccharacters"
    }
    if (Test-Path $script:SettingsPath) {
        $loaded = Get-Content $script:SettingsPath -Raw | ConvertFrom-Json
        foreach ($key in @($defaults.Keys)) {
            $prop = $loaded.PSObject.Properties[$key]
            if ($prop -and $null -ne $prop.Value -and "$($prop.Value)" -ne "") {
                $defaults[$key] = $prop.Value
            }
        }
    }
    return [pscustomobject]$defaults
}

function Save-Settings($Settings) {
    $Settings | ConvertTo-Json | Set-Content -Path $script:SettingsPath -Encoding ASCII
}

function Test-Http([string]$Url) {
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}
```

- [ ] **Step 2: Write .gitignore**

```text
settings.json
```

- [ ] **Step 3: Syntax-validate**

Run: `~/pwsh/pwsh -NoProfile -Command '$errs=$null; [System.Management.Automation.Language.Parser]::ParseFile("/workspace/playerbots/humanlike/scripts/common.ps1",[ref]$null,[ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { "syntax OK" }'`
Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots
git add humanlike/scripts/
git commit -m "feat(scripts): shared helpers and settings persistence for setup scripts"
```

---

### Task 2: setup.ps1

**Files:**
- Create: `humanlike/scripts/setup.ps1`

**Interfaces:**
- Consumes: `common.ps1` (Task 1): `Write-Status`, `Get-Settings`, `Save-Settings`; repo files `humanlike/conf/m1-ollama-direct.conf.example`, `humanlike/conf/m2-sidecar.conf.example`, `humanlike/llm_character_card.txt`, `sidecar/config.example.toml`.
- Produces: populated `settings.json` (`serverDir`), patched `<serverDir>\aiplayerbot.conf` with the marker-delimited LLM block, deployed card file, (M2) sidecar venv + `config.toml`. `start.ps1` (Task 3) relies on `settings.json.serverDir` and the M2 venv path `sidecar\.venv\Scripts\uvicorn.exe`.

- [ ] **Step 1: Write setup.ps1**

```powershell
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
    $pyVersion = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
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

$blockLines = Get-Content (Join-Path $HumanlikeDir "conf\m1-ollama-direct.conf.example")
if ($Milestone -eq "M2") {
    $m2Lines  = Get-Content (Join-Path $HumanlikeDir "conf\m2-sidecar.conf.example")
    $endpoint = @($m2Lines | Where-Object { $_ -match '^AiPlayerbot\.LLMApiEndpoint\s*=' })[0]
    $apiJson  = @($m2Lines | Where-Object { $_ -match '^AiPlayerbot\.LLMApiJson\s*=' })[0]
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
```

- [ ] **Step 2: Syntax-validate**

Run: `~/pwsh/pwsh -NoProfile -Command '$errs=$null; [System.Management.Automation.Language.Parser]::ParseFile("/workspace/playerbots/humanlike/scripts/setup.ps1",[ref]$null,[ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { "syntax OK" }'`
Expected: `syntax OK`

- [ ] **Step 3: Manual logic review against the checklist**

Confirm by reading (record answers in your report): (a) every external command result is checked (`$LASTEXITCODE` after winget/ollama/python/pip); (b) re-run path hits `[skipped]` for Ollama, venv, config.toml, cards; (c) conf patch is inside backup-success guard; (d) marker block strip means a second run cannot duplicate the block; (e) M2 block = M1 block with exactly the two keys replaced.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots
git add humanlike/scripts/setup.ps1
git commit -m "feat(scripts): one-time idempotent setup.ps1 (Ollama, models, sidecar, conf patch, cards)"
```

---

### Task 3: start.ps1

**Files:**
- Create: `humanlike/scripts/start.ps1`

**Interfaces:**
- Consumes: `common.ps1` (`Write-Status`, `Get-Settings`, `Test-Http`); `settings.json.serverDir` (Task 2); sidecar venv `sidecar\.venv\Scripts\uvicorn.exe` (Task 2, M2).
- Produces: running services (Ollama, sidecar, optionally realmd+mangosd), each in its own window.

- [ ] **Step 1: Write start.ps1**

```powershell
<#
.SYNOPSIS
Per-session ordered startup: Ollama -> sidecar (M2) -> game server (optional).
.EXAMPLE
powershell -ExecutionPolicy Bypass -File start.ps1
.EXAMPLE
powershell -ExecutionPolicy Bypass -File start.ps1 -Server
#>
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
    if (Test-Path (Join-Path $SidecarDir "config.toml")) { $Milestone = "M2" } else { $Milestone = "M1" }
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
```

- [ ] **Step 2: Syntax-validate**

Run: `~/pwsh/pwsh -NoProfile -Command '$errs=$null; [System.Management.Automation.Language.Parser]::ParseFile("/workspace/playerbots/humanlike/scripts/start.ps1",[ref]$null,[ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { "syntax OK" }'`
Expected: `syntax OK`

- [ ] **Step 3: Manual logic review**

Confirm by reading (record in report): (a) fail-fast — each ✗ exits non-zero with the failing URL/command and likely fix; (b) already-running services are detected and skipped, so re-running start.ps1 is harmless; (c) `-Server` without saved settings fails with an actionable message rather than a stack trace.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots
git add humanlike/scripts/start.ps1
git commit -m "feat(scripts): per-session start.ps1 with ordered health-checked startup"
```

---

### Task 4: pick-bots.ps1

**Files:**
- Create: `humanlike/scripts/pick-bots.ps1`

**Interfaces:**
- Consumes: `common.ps1` (`Write-Status`, `Get-Settings`, `Save-Settings`); `sidecar/config.example.toml`; `humanlike/llm_character_card.txt` (append-only).
- Produces: `inner_circle = [...]` line in `sidecar\config.toml`; `Name:: ` stub lines appended to `humanlike\llm_character_card.txt`; persisted DB host/user/name (never the password) in `settings.json`.

- [ ] **Step 1: Write pick-bots.ps1**

```powershell
<#
.SYNOPSIS
Pick your companion bots from the characters database; writes inner_circle
(sidecar\config.toml) and character-card stubs (humanlike\llm_character_card.txt).
.EXAMPLE
powershell -ExecutionPolicy Bypass -File pick-bots.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$RepoRoot     = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$SidecarDir   = Join-Path $RepoRoot "sidecar"
$HumanlikeDir = Join-Path $RepoRoot "humanlike"

# --- 1. Locate mysql.exe -----------------------------------------------------
$mysqlCmd = Get-Command mysql -ErrorAction SilentlyContinue
if ($mysqlCmd) {
    $mysqlPath = $mysqlCmd.Source
} else {
    $candidates = @(
        "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe",
        "C:\Program Files\MySQL\MySQL Server 5.7\bin\mysql.exe",
        "C:\Program Files\MariaDB 10.6\bin\mysql.exe",
        "C:\Program Files\MariaDB 11.4\bin\mysql.exe"
    )
    $mysqlPath = @($candidates | Where-Object { Test-Path $_ })[0]
    if (-not $mysqlPath) {
        $mysqlPath = Read-Host "mysql.exe not found - enter the full path to mysql.exe"
        if (-not (Test-Path $mysqlPath)) { Write-Status "FAILED" "No mysql.exe at $mysqlPath"; exit 1 }
    }
}
Write-Status "ok" "Using $mysqlPath"

# --- 2. Connection details (password never stored) ---------------------------
$settings = Get-Settings
$dbHost = Read-Host "DB host [$($settings.dbHost)]"
if (-not $dbHost) { $dbHost = $settings.dbHost }
$dbUser = Read-Host "DB user [$($settings.dbUser)]"
if (-not $dbUser) { $dbUser = $settings.dbUser }
$dbName = Read-Host "Characters DB name [$($settings.dbName)]"
if (-not $dbName) { $dbName = $settings.dbName }
$securePwd = Read-Host "DB password (input hidden)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
$plainPwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

$settings.dbHost = $dbHost
$settings.dbUser = $dbUser
$settings.dbName = $dbName
Save-Settings $settings

# --- 3. Query character names ------------------------------------------------
$env:MYSQL_PWD = $plainPwd
try {
    $names = & $mysqlPath -h $dbHost -u $dbUser -N -B -e "SELECT name FROM characters ORDER BY name" $dbName
} finally {
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    $plainPwd = $null
}
if ($LASTEXITCODE -ne 0) {
    Write-Status "FAILED" "mysql query failed - check host/user/password/database name"
    exit 1
}
$names = @($names | Where-Object { $_ })
if ($names.Count -eq 0) {
    Write-Status "FAILED" "No characters found in $dbName.characters"
    exit 1
}

# --- 4. Pick -----------------------------------------------------------------
for ($i = 0; $i -lt $names.Count; $i++) {
    Write-Host ("{0,4}. {1}" -f ($i + 1), $names[$i])
}
$selection = Read-Host "Pick your companion bots (numbers/ranges, e.g. 1,3,7-9)"
$indexes = @()
foreach ($part in $selection.Split(',')) {
    $part = $part.Trim()
    if ($part -match '^(\d+)-(\d+)$') {
        $indexes += ([int]$Matches[1])..([int]$Matches[2])
    } elseif ($part -match '^\d+$') {
        $indexes += [int]$part
    }
}
$pickedNames = @($indexes | Sort-Object -Unique |
    Where-Object { $_ -ge 1 -and $_ -le $names.Count } |
    ForEach-Object { $names[$_ - 1] })
if ($pickedNames.Count -eq 0) {
    Write-Status "FAILED" "Nothing selected"
    exit 1
}
Write-Status "ok" ("Selected: " + ($pickedNames -join ", "))

# --- 5. inner_circle in sidecar\config.toml ----------------------------------
$configToml = Join-Path $SidecarDir "config.toml"
if (-not (Test-Path $configToml)) {
    Copy-Item (Join-Path $SidecarDir "config.example.toml") $configToml
    Write-Status "done" "sidecar\config.toml created from example"
}
$tomlList = ($pickedNames | ForEach-Object { '"' + $_ + '"' }) -join ", "
$innerLine = "inner_circle = [$tomlList]"
$lines = Get-Content $configToml
$replaced = $false
$lines = $lines | ForEach-Object {
    if ($_ -match '^\s*inner_circle\s*=') { $replaced = $true; $innerLine } else { $_ }
}
if (-not $replaced) { $lines = @($lines) + $innerLine }
Set-Content -Path $configToml -Value $lines -Encoding ASCII
Write-Status "done" "inner_circle updated in sidecar\config.toml"

# --- 6. Card stubs -----------------------------------------------------------
$cardFile = Join-Path $HumanlikeDir "llm_character_card.txt"
$existingNames = @(Get-Content $cardFile |
    Where-Object { $_ -notmatch '^\s*#' -and $_ -match '::' } |
    ForEach-Object { ($_ -split '::')[0].Trim() })
$stubs = @($pickedNames | Where-Object { $existingNames -notcontains $_ } |
    ForEach-Object { "$($_):: " })
if ($stubs.Count -gt 0) {
    Add-Content -Path $cardFile -Value $stubs
    Write-Status "done" "Added $($stubs.Count) card stub(s) to humanlike\llm_character_card.txt"
} else {
    Write-Status "skipped" "All selected bots already have card lines"
}

Write-Host ""
Write-Host "Next: give each stub a personality (edit humanlike\llm_character_card.txt),"
Write-Host "then re-run setup.ps1 to deploy the cards and restart the server to load them."
```

- [ ] **Step 2: Syntax-validate**

Run: `~/pwsh/pwsh -NoProfile -Command '$errs=$null; [System.Management.Automation.Language.Parser]::ParseFile("/workspace/playerbots/humanlike/scripts/pick-bots.ps1",[ref]$null,[ref]$errs) | Out-Null; if ($errs) { $errs; exit 1 } else { "syntax OK" }'`
Expected: `syntax OK`

- [ ] **Step 3: Manual logic review**

Confirm by reading (record in report): (a) password flows only through `MYSQL_PWD` inside try/finally and is nulled after; never written to settings.json or command line; (b) range parser handles `1,3,7-9`, out-of-range numbers dropped, duplicates de-duped; (c) card append never rewrites existing lines; (d) config.toml edit replaces exactly the `inner_circle` line and appends if missing.

- [ ] **Step 4: Commit**

```bash
cd /workspace/playerbots
git add humanlike/scripts/pick-bots.ps1
git commit -m "feat(scripts): pick-bots.ps1 - DB-driven inner_circle and card stubs"
```

---

### Task 5: README integration + regression gate

**Files:**
- Modify: `humanlike/README.md` (insert "Automated setup" subsections; keep all existing content)

**Interfaces:**
- Consumes: script names/flags exactly as created in Tasks 2–4.

- [ ] **Step 1: Insert the M1 automated-setup section**

In `humanlike/README.md`, directly under the `## Milestone 1 — LLM chat direct to Ollama (no code changes)` heading (before `### 1. Install Ollama and pull models`), insert:

```markdown
### Automated setup (recommended)

From the repo checkout, in PowerShell:

```powershell
cd humanlike\scripts
powershell -ExecutionPolicy Bypass -File setup.ps1            # install + configure (M1)
powershell -ExecutionPolicy Bypass -File pick-bots.ps1        # choose companion bots from your DB
# edit humanlike\llm_character_card.txt (personality per bot), then:
powershell -ExecutionPolicy Bypass -File setup.ps1            # re-run to deploy the cards
powershell -ExecutionPolicy Bypass -File start.ps1            # start Ollama (add -Server to also start the game server)
```

`setup.ps1` is idempotent — re-running it skips finished steps. It backs up
`aiplayerbot.conf` (timestamped `.bak-*`) before patching. The manual steps
below do the same things by hand and serve as reference/fallback.
```

- [ ] **Step 2: Insert the M2 automated-setup section**

Directly under the `## Milestone 2 — brain sidecar (personas + relationship memory)` heading (before the "Requires:" line), insert:

```markdown
### Automated setup (recommended)

After rebuilding the server from this branch (step 1 below — the rebuild
itself is not automated):

```powershell
cd humanlike\scripts
powershell -ExecutionPolicy Bypass -File setup.ps1 -Milestone M2   # models, venv, config, conf patch
powershell -ExecutionPolicy Bypass -File start.ps1                 # Ollama + sidecar (add -Server for the game server)
```

The manual steps below are the reference/fallback.
```

- [ ] **Step 3: Append script verification steps to the M2 checklist**

At the end of the existing `### 4. Verify (M2 checklist)` numbered list, append:

```markdown
8. Script check: run `setup.ps1 -Milestone M2` a second time — every step
   should print `[skipped]` or `[done]` with no duplicate LLM block in
   `aiplayerbot.conf` (search for exactly one `BEGIN humanlike-llm block`).
9. Script check: run `start.ps1` while everything is already running — all
   services should report `[ok] ... already running`.
```

- [ ] **Step 4: Regression gate — sidecar suite still green**

Run: `cd /workspace/playerbots/sidecar && .venv/bin/pytest -q`
Expected: `37 passed`

- [ ] **Step 5: Syntax-validate all three scripts once more (post-review safety)**

Run (from `/workspace/playerbots`):
```bash
for f in humanlike/scripts/common.ps1 humanlike/scripts/setup.ps1 humanlike/scripts/start.ps1 humanlike/scripts/pick-bots.ps1; do
  ~/pwsh/pwsh -NoProfile -Command "\$errs=\$null; [System.Management.Automation.Language.Parser]::ParseFile('/workspace/playerbots/$f',[ref]\$null,[ref]\$errs) | Out-Null; if (\$errs) { \$errs; exit 1 } else { Write-Output '$f: syntax OK' }" || exit 1
done
```
Expected: four `syntax OK` lines.

- [ ] **Step 6: Commit**

```bash
cd /workspace/playerbots
git add humanlike/README.md
git commit -m "docs(scripts): automated-setup sections and script verification checklist"
```

---

## Verification (overall)

- **This machine:** all four .ps1 files parse cleanly under pwsh 7.4.11; sidecar suite still 37/37; one commit per task on `feature/humanlike-llm-bots`.
- **Target machine (Andreas):** README M1/M2 automated paths — `setup.ps1` twice (second run all `[skipped]`/`[done]`, single marker block), `pick-bots.ps1` against the real DB, `start.ps1` cold and warm. These are steps 8–9 of the M2 checklist plus the M1 flow.
- **After review/fixes:** push branch (updates PR #1).
