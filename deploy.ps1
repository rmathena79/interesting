#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy the interesting MCP server to a production directory.

.DESCRIPTION
    Copies server source files to the destination, creates a virtual environment
    if one does not exist, and installs the package. Safe to re-run - updates
    existing installations without touching .env or data\.

.PARAMETER DestDir
    Path to the production directory. Created if it does not exist.

.EXAMPLE
    .\deploy.ps1 -DestDir C:\Users\you\interesting-prod
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$DestDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = $PSScriptRoot
$DestDir  = [System.IO.Path]::GetFullPath($DestDir)

Write-Host "Deploying to: $DestDir"

# 1. Create destination directory
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

# 2. Mirror source tree (purges stale .pyc / deleted files)
Write-Host "Syncing src\ ..."
robocopy "$RepoRoot\src" "$DestDir\src" /E /MIR /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -gt 7) {
    Write-Error "robocopy failed with exit code $LASTEXITCODE"
    exit 1
}

# 3. Copy supporting files
Write-Host "Copying project files ..."
foreach ($file in @("pyproject.toml", "interesting-mcp-reference.md", "launch.ps1", "launch.bat")) {
    Copy-Item -Path "$RepoRoot\$file" -Destination "$DestDir\$file" -Force
}

# 4. Create virtual environment if absent
$venvPython = "$DestDir\.venv\Scripts\python.exe"
$venvPip    = "$DestDir\.venv\Scripts\pip.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment ..."
    python -m venv "$DestDir\.venv"
} else {
    Write-Host "Virtual environment already exists - skipping creation."
}

# 5. Install (or reinstall) the package
Write-Host "Installing package ..."
& $venvPip install $DestDir --quiet

Write-Host ""
Write-Host "Deployment complete."
Write-Host ""

# Remind user about .env
if (-not (Test-Path "$DestDir\.env")) {
    Write-Warning ".env not found in $DestDir"
    Write-Warning "Copy .env.example from the dev repo to $DestDir\.env and fill in your values."
} else {
    Write-Host ".env found - environment configuration present."
}
