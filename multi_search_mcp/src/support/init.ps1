[CmdletBinding()]
param(
    [string] $PythonVersion = "3.12",
    [switch] $InstallUv,
    [switch] $SkipTwitter
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))

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

Set-Location -LiteralPath $skillRoot

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

if ($SkipTwitter) {
    Write-Step "-SkipTwitter is deprecated; all project dependencies, including Twitter/X, will be installed. Cookies remain optional."
}

Write-Step "Installing all project dependencies from uv.lock"
Invoke-Native "uv" @("sync", "--locked", "--python", $PythonVersion)

Write-Step "Running multi-search doctor"
Invoke-Native "uv" @("run", "--no-sync", "multi-search", "doctor")

Write-Output ""
Write-Output "Done. Run the CLI or MCP server from this project with:"
Write-Output '  uv run --no-sync multi-search doctor'
Write-Output '  uv run --no-sync multi-search-mcp'
Write-Output "Twitter/X still requires cookies with auth_token and ct0 in ~/.search-keys.json, or TWITTER_COOKIES_PATH."
