# Read-only Windows check. Does not install, enable, stop or launch Clara.
[CmdletBinding()]
param(
    [string]$ApplicationFolder = (Join-Path $env:LOCALAPPDATA 'ClaraAgent'),
    [string]$ProbePath = (Join-Path $PSScriptRoot 'clara\windows_activity.py')
)
$ErrorActionPreference = 'Stop'
$ClaraDesktopPython = Join-Path $ApplicationFolder '.portable-desktop\python.exe'
if (-not (Test-Path -LiteralPath $ClaraDesktopPython)) {
    $ClaraDesktopPython = Join-Path $ApplicationFolder '.windows-venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $ClaraDesktopPython)) { throw 'Clara desktop Python was not found in the application folder.' }
if (-not (Test-Path -LiteralPath $ProbePath)) { throw 'The Windows observation script is missing.' }
$ClaraStart = New-Object System.Diagnostics.ProcessStartInfo
$ClaraStart.FileName = $ClaraDesktopPython
$ClaraStart.Arguments = '"' + $ProbePath + '" ' + $PID
$ClaraStart.UseShellExecute = $false
$ClaraStart.CreateNoWindow = $true
$ClaraStart.RedirectStandardOutput = $true
$ClaraStart.RedirectStandardError = $true
$ClaraProbe = New-Object System.Diagnostics.Process
$ClaraProbe.StartInfo = $ClaraStart
try {
    [void]$ClaraProbe.Start()
    $ClaraOutput = $ClaraProbe.StandardOutput.ReadToEndAsync()
    $ClaraErrors = $ClaraProbe.StandardError.ReadToEndAsync()
    if (-not $ClaraProbe.WaitForExit(12000)) {
        $ClaraProbe.Kill()
        $ClaraProbe.WaitForExit()
        throw 'The read-only Windows check timed out. No application was closed.'
    }
    $ClaraJson = $ClaraOutput.GetAwaiter().GetResult()
    if ($ClaraJson.Length -gt 1000000) { throw 'The observation was too large; it was not treated as complete.' }
    $ClaraResult = $ClaraJson | ConvertFrom-Json
    $ClaraReportFolder = Join-Path $env:LOCALAPPDATA 'Clara\diagnostics'
    New-Item -ItemType Directory -Force -Path $ClaraReportFolder | Out-Null
    $ClaraReport = Join-Path $ClaraReportFolder ('worker-check-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json')
    [System.IO.File]::WriteAllText($ClaraReport, $ClaraJson, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Report: $ClaraReport" -ForegroundColor Green
    Write-Host ('Interactive session: ' + $ClaraResult.interactive)
    Write-Host ('Observed processes: ' + @($ClaraResult.processes).Count + '; print jobs: ' + @($ClaraResult.print_jobs).Count)
    Write-Host 'This is a read-only check. Clara and the portal have not been updated or enabled.'
    if ($ClaraProbe.ExitCode -ne 0 -or @($ClaraResult.errors).Count -gt 0) {
        Write-Warning 'Some Windows observations are unavailable. Share the report so we can check them.'
    }
} finally {
    $ClaraProbe.Dispose()
}
