# Real Windows DPAPI/process/lock checks with synthetic keys and isolated data.
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
. (Join-Path $Root 'scripts\Portal-Credential.ps1')
$ClaraTestRoot = Join-Path $env:TEMP ('clara-portal-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $ClaraTestRoot | Out-Null
$ClaraTestKeyText = 'cw_' + ('a' * 64)
$ClaraTestKey = ConvertTo-SecureString $ClaraTestKeyText -AsPlainText -Force
$ClaraTestId = '2db2e159-69ab-4916-9238-e75f2b4bfe47'
$ClaraTestUrl = 'https://example.invalid/functions/v1'
$ClaraTestPython = (Get-Command python).Source
$ClaraOriginalKey = [Environment]::GetEnvironmentVariable('CLARA_PORTAL_WORKER_KEY', 'Process')
function Assert-Clara($Condition, $Message) { if (-not $Condition) { throw $Message } }
function Assert-ClaraFailure([scriptblock]$Action, [string]$Message) {
    $ClaraFailed = $false
    try { & $Action } catch { $ClaraFailed = $true }
    Assert-Clara $ClaraFailed $Message
}
try {
    Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId 'http://example.invalid/functions/v1' $ClaraTestKey } 'Insecure URL accepted.'
    Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot 'not-a-uuid' $ClaraTestUrl $ClaraTestKey } 'Invalid worker accepted.'
    $ClaraInvalidKey = ConvertTo-SecureString 'invalid' -AsPlainText -Force
    try { Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId $ClaraTestUrl $ClaraInvalidKey } 'Invalid key accepted.' }
    finally { $ClaraInvalidKey.Dispose() }
    Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId $ClaraTestUrl $ClaraTestKey
    $ClaraTestConfigPath = Join-Path $ClaraTestRoot 'portal.json'
    $ClaraTestConfig = Get-Content $ClaraTestConfigPath -Raw | ConvertFrom-Json
    Assert-Clara (-not $ClaraTestConfig.enabled -and -not $ClaraTestConfig.windows_handoff.qualified) 'Setup must not enable work or qualify the RDP.'
    Assert-Clara ($ClaraTestConfig.worker_id -eq $ClaraTestId) 'Wrong worker ID.'
    $ClaraTestEncrypted = Get-Content (Join-Path $ClaraTestRoot $ClaraTestConfig.credential_file) -Raw
    Assert-Clara (-not $ClaraTestEncrypted.Contains($ClaraTestKeyText)) 'Plaintext key was stored.'
    Assert-Clara (-not (Get-Content $ClaraTestConfigPath -Raw).Contains($ClaraTestKeyText)) 'Plaintext key in config.'
    $ClaraTestProbe = Join-Path $ClaraTestRoot 'probe.py'
    @'
import os, sys
sys.path.insert(0, sys.argv[1])
from clara.auth import sanitize_process_environment, portal_credential, clean_environment
expected = 'cw_' + 'a' * 64
assert os.environ['CLARA_PORTAL_WORKER_KEY'] == expected
sanitize_process_environment()
assert 'CLARA_PORTAL_WORKER_KEY' not in os.environ
assert portal_credential('CLARA_PORTAL_WORKER_KEY') == expected
assert 'CLARA_PORTAL_WORKER_KEY' not in clean_environment()
'@ | Set-Content -Path $ClaraTestProbe -Encoding UTF8
    $env:CLARA_PORTAL_WORKER_KEY = 'parent-value'
    $ClaraTestConfig.enabled = $true
    $ClaraTestConfig | ConvertTo-Json -Depth 5 | Set-Content $ClaraTestConfigPath -Encoding UTF8
    Invoke-ClaraPortalProcess $ClaraTestRoot $ClaraTestPython @($ClaraTestProbe, $Root)
    Assert-Clara ($script:ClaraProcessExitCode -eq 0) 'Encrypted key did not reach service-only credential memory.'
    Assert-Clara ($env:CLARA_PORTAL_WORKER_KEY -eq 'parent-value') 'Parent environment was not restored.'
    Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId $ClaraTestUrl $ClaraTestKey } 'Active configuration was replaced.'
    $ClaraTestConfig.enabled = $false
    $ClaraTestConfig | ConvertTo-Json -Depth 5 | Set-Content $ClaraTestConfigPath -Encoding UTF8
    Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot ([guid]::NewGuid().ToString()) $ClaraTestUrl $ClaraTestKey } 'Different worker was replaced.'
    # Python's real single_instance lock must also stop PowerShell setup.
    $ClaraTestLockProbe = Join-Path $ClaraTestRoot 'lock.py'
    @'
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from clara.instance import single_instance
with single_instance(Path(sys.argv[2])):
    Path(sys.argv[2], 'locked').touch()
    time.sleep(25)
'@ | Set-Content -Path $ClaraTestLockProbe -Encoding UTF8
    $ClaraLockArguments = '"{0}" "{1}" "{2}"' -f $ClaraTestLockProbe, $Root, $ClaraTestRoot
    $ClaraLockProcess = Start-Process -FilePath $ClaraTestPython -ArgumentList $ClaraLockArguments -PassThru -WindowStyle Hidden
    try {
        $ClaraLockDeadline = [DateTime]::UtcNow.AddSeconds(10)
        while (-not (Test-Path (Join-Path $ClaraTestRoot 'locked')) -and [DateTime]::UtcNow -lt $ClaraLockDeadline) { Start-Sleep -Milliseconds 100 }
        Assert-Clara (Test-Path (Join-Path $ClaraTestRoot 'locked')) 'Python lock probe did not start.'
        Assert-ClaraFailure { Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId $ClaraTestUrl $ClaraTestKey } 'Running Clara lock was ignored.'
    } finally { if (-not $ClaraLockProcess.HasExited) { $ClaraLockProcess.Kill(); $ClaraLockProcess.WaitForExit() } }
    Save-ClaraPortalConnection $ClaraTestRoot $ClaraTestId $ClaraTestUrl $ClaraTestKey
    $ClaraTestConfig = Get-Content $ClaraTestConfigPath -Raw | ConvertFrom-Json
    $ClaraTestConfig.enabled = $true
    $ClaraOriginalFile = $ClaraTestConfig.credential_file
    $ClaraTestConfig.credential_file = '..\stolen.dpapi'
    $ClaraTestConfig | ConvertTo-Json -Depth 5 | Set-Content $ClaraTestConfigPath -Encoding UTF8
    Assert-ClaraFailure { Invoke-ClaraPortalProcess $ClaraTestRoot $ClaraTestPython @('-c', 'raise SystemExit(0)') } 'Credential path traversal accepted.'
    $ClaraTestConfig.credential_file = $ClaraOriginalFile
    $ClaraTestConfig | ConvertTo-Json -Depth 5 | Set-Content $ClaraTestConfigPath -Encoding UTF8
    [IO.File]::WriteAllText((Join-Path $ClaraTestRoot $ClaraOriginalFile), 'not-an-encrypted-key')
    Assert-ClaraFailure { Invoke-ClaraPortalProcess $ClaraTestRoot $ClaraTestPython @('-c', 'raise SystemExit(0)') } 'Corrupt key accepted.'
    Assert-Clara ($env:CLARA_PORTAL_WORKER_KEY -eq 'parent-value') 'Failed startup changed parent environment.'
    $ClaraTestConfig.enabled = $false
    $ClaraTestConfig | ConvertTo-Json -Depth 5 | Set-Content $ClaraTestConfigPath -Encoding UTF8
    Invoke-ClaraPortalProcess $ClaraTestRoot $ClaraTestPython @('-c', 'raise SystemExit(0)')
    Assert-Clara ($script:ClaraProcessExitCode -eq 0) 'Disabled connection tried decrypting its key.'
    Write-Host 'Windows portal setup: DPAPI, service-only environment, atomic rotation, process locking and failure checks passed.'
} finally {
    $ClaraTestKey.Dispose()
    [Environment]::SetEnvironmentVariable('CLARA_PORTAL_WORKER_KEY', $ClaraOriginalKey, 'Process')
    Remove-Item -LiteralPath $ClaraTestRoot -Recurse -Force
}
