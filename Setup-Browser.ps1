[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
& $ClaraPython (Join-Path $PSScriptRoot 'scripts\install-browser.py')
if ($LASTEXITCODE -ne 0) { throw 'Browser setup failed. Keep the error output for diagnosis.' }
Write-Host 'Chrome tools are installed. Restart Clara, enable Chrome in Connections, then test it.' -ForegroundColor Green
