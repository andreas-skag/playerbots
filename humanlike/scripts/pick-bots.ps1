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
