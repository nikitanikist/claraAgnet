# Exercise updater control flow without network, package installs or user data.
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$ClaraTestRoot = Join-Path $env:TEMP ('clara-update-test-' + [guid]::NewGuid().ToString('N'))
$ClaraTestData = Join-Path $ClaraTestRoot 'data'
$ClaraTestScripts = Join-Path $ClaraTestRoot 'scripts'
$ClaraRevision = 'a' * 40
$ClaraTestPython = (Get-Command python).Source
$ClaraOriginalPath = $env:Path
$ClaraOriginalReceipt = $env:CLARA_TEST_DATA
function Assert-Clara($Condition, $Message) { if (-not $Condition) { throw $Message } }
# Only the Git transport/checkout is mocked. Python, file writes and locks run.
function git {
    $global:LASTEXITCODE = 0
    $ClaraCall = $args -join ' '
    $script:ClaraCalls += $ClaraCall
    switch -Regex ($ClaraCall) {
        '^remote get-url origin$' { if ($script:ClaraCase -eq 'remote') { 'https://example.invalid/wrong.git' } else { 'https://github.com/nikitanikist/claraAgnet.git' }; break }
        '^rev-parse HEAD$' { 'b' * 40; break }
        '^status --porcelain$' { if ($script:ClaraCase -eq 'dirty') { ' M user-edit.py' }; break }
        '^fetch origin feat/clearhouse-portal-v1$' { if ($script:ClaraCase -eq 'fetch') { $global:LASTEXITCODE = 1 }; break }
        '^merge-base --is-ancestor ' { if ($script:ClaraCase -eq 'revision') { $global:LASTEXITCODE = 1 }; break }
        '^switch --detach ' { if ($script:ClaraCase -eq 'switch') { $global:LASTEXITCODE = 1 }; break }
        default { throw "Unexpected Git operation: $ClaraCall" }
    }
}
try {
    New-Item -ItemType Directory -Path $ClaraTestData, $ClaraTestScripts, (Join-Path $ClaraTestRoot '.portable-python') | Out-Null
    New-Item -ItemType File -Path (Join-Path $ClaraTestRoot '.portable-python\.clara-ready') | Out-Null
    'function Initialize-ClaraWindows { param($Root); return (Get-Command python).Source }' | Set-Content (Join-Path $ClaraTestScripts 'Windows-Environment.ps1')
    @'
import os, sys
from pathlib import Path
data = Path(sys.argv[sys.argv.index('--data-dir')+1])
(data / 'backup-ran').touch()
print('synthetic-local-backup.zip')
raise SystemExit(1 if (data / 'fail-backup').exists() else 0)
'@ | Set-Content (Join-Path $ClaraTestScripts 'backup-data.py') -Encoding UTF8
    @'
import os, msvcrt
from pathlib import Path
data = Path(os.environ['CLARA_TEST_DATA'])
with (data / 'instance.lock').open('a+b') as lock:
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        pass
    else:
        raise AssertionError('Updater did not retain the Windows instance lock')
(data / 'install-ran').touch()
raise SystemExit(1 if (data / 'fail-install').exists() else 0)
'@ | Set-Content (Join-Path $ClaraTestScripts 'install-portable.py') -Encoding UTF8
    $env:CLARA_TEST_DATA = $ClaraTestData
    foreach ($ClaraScenario in @('remote', 'dirty', 'fetch', 'revision', 'backup', 'switch', 'install', 'success')) {
        $script:ClaraCase = $ClaraScenario
        $script:ClaraCalls = @()
        foreach ($ClaraMarker in @('backup-ran', 'install-ran', 'fail-backup', 'fail-install')) {
            Remove-Item (Join-Path $ClaraTestData $ClaraMarker) -ErrorAction SilentlyContinue
        }
        if ($ClaraScenario -eq 'backup') { New-Item (Join-Path $ClaraTestData 'fail-backup') -ItemType File | Out-Null }
        if ($ClaraScenario -eq 'install') { New-Item (Join-Path $ClaraTestData 'fail-install') -ItemType File | Out-Null }
        $ClaraFailed = $false
        try { & (Join-Path $Root 'Update-ClaraPortalTest.ps1') -Revision $ClaraRevision -ApplicationFolder $ClaraTestRoot -DataFolder $ClaraTestData }
        catch { $ClaraFailed = $true }
        Assert-Clara ($ClaraFailed -eq ($ClaraScenario -ne 'success')) "Unexpected outcome: $ClaraScenario"
        $ClaraSwitched = @($script:ClaraCalls | Where-Object { $_ -like 'switch --detach *' }).Count -gt 0
        Assert-Clara ($ClaraSwitched -eq ($ClaraScenario -in @('switch', 'install', 'success'))) "Source changed before checks passed: $ClaraScenario"
        Assert-Clara ((Test-Path (Join-Path $ClaraTestData 'install-ran')) -eq ($ClaraScenario -in @('install', 'success'))) "Wrong install behavior: $ClaraScenario"
    }
    Assert-Clara (@(Get-ChildItem $ClaraTestData -Filter 'portal-test-update-*.json').Count -eq 3) 'Update receipts missing.'
    # Parse every delivered entry point with actual Windows PowerShell 5.1.
    foreach ($ClaraFile in @('Start-Clara.ps1', 'Connect-ClaraPortal.ps1', 'scripts\Portal-Credential.ps1', 'Update-ClaraPortalTest.ps1')) {
        $ClaraParseErrors = $null; $ClaraParseTokens = $null
        [Management.Automation.Language.Parser]::ParseFile((Join-Path $Root $ClaraFile), [ref]$ClaraParseTokens, [ref]$ClaraParseErrors) | Out-Null
        Assert-Clara ($ClaraParseErrors.Count -eq 0) "Invalid PowerShell: $ClaraFile"
    }
    Write-Host 'Portal test updater: eight backup/install/transport failure and success scenarios passed.'
} finally {
    $env:Path = $ClaraOriginalPath
    [Environment]::SetEnvironmentVariable('CLARA_TEST_DATA', $ClaraOriginalReceipt, 'Process')
    Remove-Item -LiteralPath $ClaraTestRoot -Recurse -Force
}
