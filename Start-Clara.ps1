[CmdletBinding()]
param([int]$Port = 8876, [switch]$NoOpen)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
$ClaraArguments = @('-m', 'clara', 'serve', '--port', "$Port")
if ($NoOpen) { $ClaraArguments += '--no-open' }
& $ClaraPython @ClaraArguments
exit $LASTEXITCODE
