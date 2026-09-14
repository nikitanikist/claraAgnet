[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WorkerId,
    [Parameter(Mandatory = $true)][string]$FunctionsUrl,
    [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara')
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\Portal-Credential.ps1')
Write-Host 'Use the dedicated Clara Windows account. Stop the idle Clara CLI before saving this connection.'
Write-Host 'Clara will use this Windows account and its existing Claude sign-in. Portal execution stays disabled during setup.'
$ClaraWorkerKey = Read-Host 'Paste the worker key from Clara Settings (input is hidden)' -AsSecureString
try {
    Save-ClaraPortalConnection -DataFolder $DataFolder -WorkerId $WorkerId -FunctionsUrl $FunctionsUrl -Key $ClaraWorkerKey
} finally {
    $ClaraWorkerKey.Dispose()
}
Write-Host 'Connection saved with Windows encryption. Execution is still disabled; the key is not shown or sent anywhere.' -ForegroundColor Green
Write-Host 'Keep the existing portal runner. The next step is a controlled connection test.'
