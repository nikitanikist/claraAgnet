[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$JobId,
    [Parameter(Mandatory = $true)][string]$WorkerId,
    [Parameter(Mandatory = $true)][int]$Attempt,
    [Parameter(Mandatory = $true)][long]$Fence,
    [string[]]$Operation = @(),
    [Parameter(Mandatory = $true)][string]$Note,
    [switch]$ConfirmDesktopIdle,
    [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara')
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
$ClaraArguments = @('-m', 'clara.portal_hold_review', '--data-dir', $DataFolder,
    '--job-id', $JobId, '--worker-id', $WorkerId, '--attempt', "$Attempt", '--fence', "$Fence", '--note', $Note)
foreach ($ClaraOperation in $Operation) { $ClaraArguments += @('--operation', $ClaraOperation) }
if ($ConfirmDesktopIdle) { $ClaraArguments += '--confirm-desktop-idle' }
. (Join-Path $PSScriptRoot 'scripts\Portal-Credential.ps1')
Invoke-ClaraPortalProcess -DataFolder $DataFolder -Python $ClaraPython -Arguments $ClaraArguments
exit $script:ClaraProcessExitCode
