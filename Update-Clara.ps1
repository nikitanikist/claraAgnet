# Run after stopping Clara. Uses your existing non-admin portable installation.
[CmdletBinding()]
param([switch]$SkipBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
& $ClaraPython (Join-Path $PSScriptRoot 'scripts\backup-data.py')
if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Stop Clara before updating.' }
$ClaraBefore = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'This updater requires a Git checkout.' }
$ClaraEdits = & git status --porcelain
if ($ClaraEdits) { throw 'Save local source edits before updating. Your data backup has been created.' }
& git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Git update failed. Your data backup is available.' }
$ClaraInstallArgs = @((Join-Path $PSScriptRoot 'scripts\install-portable.py'))
if ($SkipBrowser) { $ClaraInstallArgs += '--skip-browser' }
if (Test-Path (Join-Path $PSScriptRoot '.portable-python\.clara-ready')) {
    & $ClaraPython @ClaraInstallArgs
} else {
    & (Join-Path $PSScriptRoot 'Install-Clara.ps1') -SkipBrowser:$SkipBrowser
}
if ($LASTEXITCODE -ne 0) { throw "Setup failed. Previous source revision: $ClaraBefore. See docs/UPDATE-AND-ROLLBACK.md." }
Write-Host 'Update installed. Run Start-Clara.ps1, then test Chrome and the Windows test workflow.' -ForegroundColor Green
