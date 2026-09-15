[CmdletBinding()]
param([switch]$Disable, [switch]$Start, [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara'))
$ErrorActionPreference = 'Stop'
$ClaraIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$ClaraSid = $ClaraIdentity.User.Value
$ClaraTaskName = 'Clara-' + $ClaraSid
$ClaraRunner = Join-Path $PSScriptRoot 'Run-ClaraAutomatic.ps1'
$ClaraStartup = [Environment]::GetFolderPath('Startup')
$ClaraLinkPath = Join-Path $ClaraStartup 'Clara automatic startup.lnk'
$ClaraPause = Join-Path $DataFolder 'autostart-paused'
New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
$ClaraExisting = Get-ScheduledTask -TaskName $ClaraTaskName -ErrorAction SilentlyContinue
if ($ClaraExisting -and (@($ClaraExisting.Actions).Count -ne 1 -or -not $ClaraExisting.Actions[0].Arguments.Contains($ClaraRunner))) {
    throw 'A different task already uses this name. Existing tasks were not changed.'
}
if ($Disable) {
    [IO.File]::WriteAllText($ClaraPause, 'Automatic startup paused by operator.')
    if ($ClaraExisting) { Disable-ScheduledTask -TaskName $ClaraTaskName | Out-Null }
    if (Test-Path -LiteralPath $ClaraLinkPath) { Remove-Item -LiteralPath $ClaraLinkPath }
    Write-Host 'Automatic startup paused. The current Clara process and its work have not been stopped.'
    exit 0
}
if (-not (Test-Path -LiteralPath $ClaraRunner)) { throw 'The automatic Clara launcher is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $DataFolder 'portal.json'))) { throw 'Connect this Windows account to the portal first.' }
$ClaraPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$ClaraArguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -DataFolder "{1}"' -f $ClaraRunner, $DataFolder
$ClaraAction = New-ScheduledTaskAction -Execute $ClaraPowerShell -Argument $ClaraArguments -WorkingDirectory $PSScriptRoot
$ClaraLogon = New-ScheduledTaskTrigger -AtLogOn -User $ClaraSid
# The minute trigger recovers even a clean unexpected exit. IgnoreNew and the
# application OS lock prevent overlap with an existing scheduled/manual worker.
$ClaraRetry = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$ClaraPrincipal = New-ScheduledTaskPrincipal -UserId $ClaraSid -LogonType Interactive -RunLevel Limited
$ClaraSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $ClaraTaskName -Action $ClaraAction -Trigger @($ClaraLogon, $ClaraRetry) -Principal $ClaraPrincipal -Settings $ClaraSettings -Description 'Runs Clara in this signed-in Windows account. One worker; restart after exit; no automatic replay of interrupted work.' -Force | Out-Null

# This account-level sign-in entry re-registers the task when a roaming profile
# lands on a different RDP host. No machine/RDP name is hard-coded.
New-Item -ItemType Directory -Force -Path $ClaraStartup | Out-Null
$ClaraShell = New-Object -ComObject WScript.Shell
$ClaraLink = $ClaraShell.CreateShortcut($ClaraLinkPath)
$ClaraLink.TargetPath = $ClaraPowerShell
$ClaraLink.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -DataFolder "{1}" -Start' -f $PSCommandPath, $DataFolder
$ClaraLink.WorkingDirectory = $PSScriptRoot
$ClaraLink.Description = 'Start Clara for the signed-in Windows account'
$ClaraLink.WindowStyle = 7
$ClaraLink.Save()
if (Test-Path -LiteralPath $ClaraPause) { Remove-Item -LiteralPath $ClaraPause }
if ($Start) { Start-ScheduledTask -TaskName $ClaraTaskName }
Write-Host 'Automatic startup enabled for this Windows account. Clara starts at sign-in and restarts within about one minute after exit.' -ForegroundColor Green
Write-Host ('Task: ' + $ClaraTaskName)
Write-Host 'Keep the dedicated Windows desktop signed in and unlocked for application work. Website sign-in does not unlock Windows.'
