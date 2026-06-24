[CmdletBinding()]
param(
    [string] $PythonVersion = "3.12",
    [switch] $InstallUv,
    [switch] $SkipTwitter
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))
$mcpRoot = Join-Path $skillRoot "mcp"
$venvPython = Join-Path $skillRoot ".venv\Scripts\python.exe"

function Write-Step {
    param([string] $Message)
    Write-Output "==> $Message"
}

function Test-Command {
    param([string] $Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-Native {
    param(
        [string] $Command,
        [string[]] $Arguments
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

Set-Location $skillRoot

Write-Step "Checking uv"
if (-not (Test-Command "uv")) {
    if (-not $InstallUv) {
        Write-Output "uv was not found. Re-run with -InstallUv, or install it manually:"
        Write-Output "  winget install --id astral-sh.uv -e"
        exit 1
    }
    if (-not (Test-Command "winget")) {
        Write-Output "winget was not found. Install uv manually from https://docs.astral.sh/uv/"
        exit 1
    }
    Write-Step "Installing uv with winget"
    Invoke-Native "winget" @("install", "--id", "astral-sh.uv", "-e")
}

Write-Step "Installing Python $PythonVersion through uv if needed"
Invoke-Native "uv" @("python", "install", $PythonVersion)

if (Test-Path $venvPython) {
    Write-Step "Using existing local virtual environment"
} else {
    Write-Step "Creating local virtual environment"
    Invoke-Native "uv" @("venv", "--python", $PythonVersion)
}

if (-not $SkipTwitter) {
    Write-Step "Installing Twitter/X optional dependency"
    Invoke-Native "uv" @("pip", "install", "twikit-ng")
} else {
    Write-Step "Skipping Twitter/X optional dependency"
}

Write-Step "Running multi-search doctor"
Invoke-Native "uv" @("run", "python", "-c", "import sys; sys.path.insert(0, r'$mcpRoot'); from src.service import doctor_data; import json; print(json.dumps(doctor_data(include_keys=True, include_network=False), ensure_ascii=False, indent=2))")

Write-Output ""
Write-Output "Done. Run the MCP server with:"
Write-Output '  python mcp/server.py'
