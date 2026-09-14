[CmdletBinding()]
param([int]$Port = 8876, [switch]$NoOpen, [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara'))
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
$ClaraArguments = @('-m', 'clara', 'serve', '--port', "$Port", '--data-dir', $DataFolder)
if ($NoOpen) { $ClaraArguments += '--no-open' }
. (Join-Path $PSScriptRoot 'scripts\Portal-Credential.ps1')
Invoke-ClaraPortalProcess -DataFolder $DataFolder -Python $ClaraPython -Arguments $ClaraArguments
exit $script:ClaraProcessExitCode
