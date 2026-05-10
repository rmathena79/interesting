#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Always run relative to this script's own directory so data\ lands in the prod dir
Set-Location $PSScriptRoot

# Load .env
$envFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Length -eq 2) {
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
} else {
    Write-Warning ".env not found - starting with system environment variables only."
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Python not found at $python - run deploy.ps1 first."
    exit 1
}

# Launch a minimized console window; /k keeps it open after the server exits
Start-Process cmd `
    -ArgumentList "/k", "title Interesting MCP Server & `"$python`" -m interesting.server" `
    -WindowStyle Minimized `
    -WorkingDirectory $PSScriptRoot
