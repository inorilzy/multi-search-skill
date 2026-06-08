[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$skillRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$searchPy = Join-Path $skillRoot "search.py"
$venvPython = Join-Path $skillRoot ".venv\Scripts\python.exe"

function Write-Check {
    param(
        [bool] $Ok,
        [string] $Name,
        [string] $Detail = ""
    )
    $mark = if ($Ok) { "OK" } else { "WARN" }
    if ($Detail) {
        Write-Output "[$mark] $Name - $Detail"
    } else {
        Write-Output "[$mark] $Name"
    }
}

function Test-PythonCommand {
    param([string[]] $Command)

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Command[0]
        $args = @()
        if ($Command.Length -gt 1) {
            $args += $Command[1..($Command.Length - 1)]
        }
        $args += "--version"
        $psi.Arguments = ($args | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEnd().Trim()
        $stderr = $proc.StandardError.ReadToEnd().Trim()
        $proc.WaitForExit()
        $detail = (($stdout, $stderr) | Where-Object { $_ }) -join " | "
        if ($proc.ExitCode -eq 0) {
            return [pscustomobject]@{ Ok = $true; Command = $Command; Detail = $detail }
        }
        return [pscustomobject]@{ Ok = $false; Command = $Command; Detail = $detail }
    } catch {
        return [pscustomobject]@{ Ok = $false; Command = $Command; Detail = $_.Exception.Message }
    }
}

Write-Output "# multi-search environment check"

$uv = Get-Command uv -ErrorAction SilentlyContinue
Write-Check ($null -ne $uv) "uv" $(if ($uv) { $uv.Source } else { "missing; run ./scripts/init.ps1 -InstallUv or winget install --id astral-sh.uv -e" })
Write-Check (Test-Path $venvPython) "local .venv" $(if (Test-Path $venvPython) { $venvPython } else { "missing; run ./scripts/init.ps1" })

$candidates = @(
    @($venvPython),
    @("python"),
    @("py", "-3"),
    @("python3")
)

$python = $null
foreach ($candidate in $candidates) {
    $result = Test-PythonCommand -Command $candidate
    Write-Check $result.Ok ("Python command: " + ($candidate -join " ")) $result.Detail
    if ($result.Ok -and -not $python) {
        $python = $candidate
    }
}

if (-not $python) {
    Write-Output ""
    if ($uv) {
        Write-Output "No usable Python command was found yet, but uv is available. Initialize this skill with:"
        Write-Output "  ./scripts/init.ps1"
    } else {
        Write-Output "No usable Python command was found. Install uv, then initialize this skill:"
        Write-Output "  winget install --id astral-sh.uv -e"
        Write-Output "  ./scripts/init.ps1"
    }
    Write-Output "If python points to Microsoft Store, you can also disable App execution aliases for python.exe / python3.exe."
    exit 1
}

Write-Output ""
Write-Output ("Using Python: " + ($python -join " "))

try {
    $pythonArgs = @()
    if ($python.Length -gt 1) {
        $pythonArgs = $python[1..($python.Length - 1)]
    }
    & $python[0] @pythonArgs $searchPy --doctor
    $doctorExit = $LASTEXITCODE
} catch {
    Write-Check $false "python search.py --doctor" $_.Exception.Message
    exit 1
}

Write-Output ""
Write-Output "Twitter/X optional setup:"
Write-Output ("  " + ($python -join " ") + " -m pip install twikit-ng")
Write-Output "  Add twitter cookies to ~/.search-keys.json with auth_token and ct0, or set TWITTER_COOKIES_PATH."

exit $doctorExit
