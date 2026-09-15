[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$JobId,
    [Parameter(Mandatory = $true)][int]$Attempt,
    [Parameter(Mandatory = $true)][long]$Fence,
    [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara'),
    [switch]$Send
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
$ClaraArguments = @('-m', 'clara.portal_recovery', '--data-dir', $DataFolder,
    '--job-id', $JobId, '--attempt', "$Attempt", '--fence', "$Fence")
if ($Send) { $ClaraArguments += '--send' }
. (Join-Path $PSScriptRoot 'scripts\Portal-Credential.ps1')
Invoke-ClaraPortalProcess -DataFolder $DataFolder -Python $ClaraPython -Arguments $ClaraArguments
exit $script:ClaraProcessExitCode
