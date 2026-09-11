# Run in the target Windows user's interactive session. No administrator required.
[CmdletBinding()]
param([switch]$SkipDesktop)
$ErrorActionPreference = 'Stop'
$ClaraRoot = $PSScriptRoot
Set-Location -LiteralPath $ClaraRoot

function Run-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

$ClaraPython = $null
$ClaraPythonPrefix = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        & py -3 -c 'import sys, venv, ensurepip; assert sys.version_info >= (3,12)' 2>$null
        if ($LASTEXITCODE -eq 0) { $ClaraPython = 'py'; $ClaraPythonPrefix = @('-3') }
    } catch { $ClaraPython = $null }
}
if (-not $ClaraPython -and (Get-Command python -ErrorAction SilentlyContinue)) {
    try {
        & python -c 'import sys, venv, ensurepip; assert sys.version_info >= (3,12)' 2>$null
        if ($LASTEXITCODE -eq 0) { $ClaraPython = 'python' }
    } catch { $ClaraPython = $null }
}
if (-not $ClaraPython) {
    throw 'Full Python 3.12+ with venv/ensurepip was not found. For an existing embeddable runtime, run scripts/install-portable.py with that python.exe. See docs/PORTABLE-WINDOWS.md.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22 LTS (22.12 or newer), reopen PowerShell, then rerun. See https://nodejs.org/en/download'
}
$ClaraNodeVersion = (& node --version).Trim().TrimStart('v').Split('.')
if ($LASTEXITCODE -ne 0 -or $ClaraNodeVersion.Count -lt 2) { throw 'Could not read Node.js version.' }
$ClaraNodeMajor = [int]$ClaraNodeVersion[0]
$ClaraNodeMinor = [int]$ClaraNodeVersion[1]
if (-not (($ClaraNodeMajor -eq 20 -and $ClaraNodeMinor -ge 19) -or ($ClaraNodeMajor -eq 22 -and $ClaraNodeMinor -ge 12) -or $ClaraNodeMajor -ge 23)) {
    throw 'Node.js does not meet the browser connector requirement.'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'npm.cmd was not found; repair the Node.js installation.' }
Write-Host 'Installing Clara and its official Claude SDK...' -ForegroundColor Cyan
if (-not (Test-Path '.venv\Scripts\python.exe')) {
    Run-Checked $ClaraPython ($ClaraPythonPrefix + @('-m', 'venv', '.venv'))
}
$ClaraVenvPython = Join-Path $ClaraRoot '.venv\Scripts\python.exe'
Run-Checked $ClaraVenvPython @('-m', 'pip', 'install', '-r', 'requirements.lock')
Run-Checked $ClaraVenvPython @('-m', 'pip', 'install', '--no-deps', '-e', '.')
Run-Checked 'npm.cmd' @('ci', '--ignore-scripts', '--no-fund', '--no-audit')
if (-not $SkipDesktop) {
    Write-Host 'Installing Windows desktop tools into a separate environment...' -ForegroundColor Cyan
    if (-not (Test-Path '.windows-venv\Scripts\python.exe')) {
        Run-Checked $ClaraPython ($ClaraPythonPrefix + @('-m', 'venv', '.windows-venv'))
    }
    $ClaraDesktopPython = Join-Path $ClaraRoot '.windows-venv\Scripts\python.exe'
    Run-Checked $ClaraDesktopPython @('-m', 'pip', 'install', '-r', 'requirements-windows-desktop.txt')
    Run-Checked $ClaraDesktopPython @('-m', 'pip', 'check')
    Run-Checked (Join-Path $ClaraRoot '.windows-venv\Scripts\windows-mcp.exe') @('serve', '--help')
}
Run-Checked $ClaraVenvPython @('-m', 'pip', 'check')
Run-Checked $ClaraVenvPython @('-m', 'clara', 'doctor')
Write-Host "`nClara is installed. Next:" -ForegroundColor Green
Write-Host '1. .\Login-Clara.ps1'
Write-Host '2. .\Start-Clara.ps1'
Write-Host '3. In Settings, add your test folder and enable the tools you want to test.'
Write-Host 'Run from the interactive RDP desktop, not a Windows service or Session 0.'
