# Task Scheduler runs this in the signed-in user's desktop, never as SYSTEM.
[CmdletBinding()]
param([string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara'))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
if (Test-Path (Join-Path $DataFolder 'autostart-paused')) { exit 0 }

# A manually started Clara is valid too. Do not start a second copy or disturb it.
$ClaraLock = [IO.File]::Open((Join-Path $DataFolder 'instance.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
try {
    try { $ClaraLock.Lock(0, 1) }
    catch { exit 0 }
    $ClaraLock.Unlock(0, 1)
} finally { $ClaraLock.Dispose() }

. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
. (Join-Path $PSScriptRoot 'scripts\Portal-Credential.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
$ClaraLogs = Join-Path $DataFolder 'logs'
New-Item -ItemType Directory -Force -Path $ClaraLogs | Out-Null
$ClaraLog = Join-Path $ClaraLogs 'automatic-start.log'
if ((Test-Path $ClaraLog) -and (Get-Item $ClaraLog).Length -gt 5MB) {
    Move-Item -LiteralPath $ClaraLog -Destination ($ClaraLog + '.previous') -Force
}
# The Python process holds its OS lock for its whole lifetime, including races
# with a manual start. Credentials stay in the existing DPAPI startup path.
try {
    # PowerShell 5 turns redirected native stderr (including ordinary Uvicorn
    # INFO messages) into ErrorRecords. Those messages must not abort startup.
    $ErrorActionPreference = 'Continue'
    Invoke-ClaraPortalProcess -DataFolder $DataFolder -Python $ClaraPython -Arguments @('-m', 'clara', 'serve', '--data-dir', $DataFolder, '--no-open') >> $ClaraLog 2>&1
    exit $script:ClaraProcessExitCode
} catch {
    # Do not log arbitrary exception strings, which may contain private details.
    Add-Content -LiteralPath $ClaraLog -Value ('{0:o} Automatic startup failed; inspect the installed runtime and saved connection.' -f [DateTime]::UtcNow)
    exit 1
}
