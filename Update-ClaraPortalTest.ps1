# Installs an explicitly reviewed integration revision. Does not start a worker.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-f0-9]{40}$')][string]$Revision,
    [string]$ApplicationFolder = (Join-Path $env:LOCALAPPDATA 'ClaraAgent'),
    [string]$DataFolder = (Join-Path $env:LOCALAPPDATA 'Clara')
)
$ErrorActionPreference = 'Stop'
$ClaraUpdateLock = $null
Push-Location -LiteralPath $ApplicationFolder
try {
    $ClaraRemote = & git remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $ClaraRemote -notmatch '^(https://github\.com/nikitanikist/claraAgnet(?:\.git)?|git@github\.com:nikitanikist/claraAgnet(?:\.git)?)$') {
        throw 'This test update requires the existing Clara Git installation.'
    }
    $ClaraBefore = & git rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the installed revision.' }
    $ClaraEdits = & git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $ClaraEdits) { throw 'Save local source edits before updating. No files have been replaced.' }
    & git fetch origin feat/clearhouse-portal-v1
    if ($LASTEXITCODE -ne 0) { throw 'Cannot download the integration update. No files have been replaced.' }
    & git merge-base --is-ancestor $Revision FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { throw 'The requested revision is not in the integration branch. No files have been replaced.' }
    . (Join-Path $ApplicationFolder 'scripts\Windows-Environment.ps1')
    $ClaraPython = Initialize-ClaraWindows $ApplicationFolder
    Write-Host 'Backing up existing Clara history. Stop the idle Clara CLI first.'
    $ClaraBackup = & $ClaraPython (Join-Path $ApplicationFolder 'scripts\backup-data.py') --data-dir $DataFolder
    if ($LASTEXITCODE -ne 0) { throw 'Backup failed. Read the error above. No files have been replaced.' }
    $ClaraUpdateLock = [IO.File]::Open((Join-Path $DataFolder 'instance.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    try { $ClaraUpdateLock.Lock(0, 1) }
    catch { throw 'Clara is still running. Stop its CLI with Ctrl+C and retry the update.' }
    $ClaraReceipt = [ordered]@{ previous_revision = "$ClaraBefore"; test_revision = $Revision; backup = @($ClaraBackup); created_at = [DateTime]::UtcNow.ToString('o') }
    $ClaraReceiptPath = Join-Path $DataFolder ('portal-test-update-' + [guid]::NewGuid().ToString('N') + '.json')
    [IO.File]::WriteAllText($ClaraReceiptPath, ($ClaraReceipt | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Write-Host "Backup: $ClaraBackup"
    Write-Host "Update record: $ClaraReceiptPath"
    & git switch --detach $Revision
    if ($LASTEXITCODE -ne 0) { throw 'Git could not select the test revision. The backup is preserved.' }
    if (Test-Path (Join-Path $ApplicationFolder '.portable-python\.clara-ready')) {
        & $ClaraPython (Join-Path $ApplicationFolder 'scripts\install-portable.py')
    } else {
        & (Join-Path $ApplicationFolder 'Install-Clara.ps1')
    }
    if ($LASTEXITCODE -ne 0) { throw "Setup failed. Previous source revision: $ClaraBefore. Keep the backup and see docs/UPDATE-AND-ROLLBACK.md." }
    Write-Host 'Portal test update installed. Clara is stopped; configure its worker connection next.' -ForegroundColor Green
} finally {
    if ($ClaraUpdateLock) { $ClaraUpdateLock.Dispose() }
    Pop-Location
}
