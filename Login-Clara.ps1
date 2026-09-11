$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. (Join-Path $PSScriptRoot 'scripts\Windows-Environment.ps1')
$ClaraPython = Initialize-ClaraWindows $PSScriptRoot
& $ClaraPython -m clara login
exit $LASTEXITCODE
