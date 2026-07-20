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
