# The worker key is protected with Windows DPAPI for this account. No model
# credentials are handled here. Plaintext is never written to a file or output.
function Save-ClaraPortalConnection {
    param([string]$DataFolder, [string]$WorkerId, [string]$FunctionsUrl, [Security.SecureString]$Key)
    $ClaraId = [guid]::Empty
    if (-not [guid]::TryParse($WorkerId, [ref]$ClaraId) -or $ClaraId -eq [guid]::Empty) { throw 'Enter the worker ID shown in Clara Settings.' }
    $ClaraUrl = $null
    if (-not [uri]::TryCreate($FunctionsUrl, [UriKind]::Absolute, [ref]$ClaraUrl) -or
        $ClaraUrl.Scheme -ne 'https' -or $ClaraUrl.UserInfo -or $ClaraUrl.Query -or $ClaraUrl.Fragment -or
        $ClaraUrl.AbsolutePath.TrimEnd('/') -ne '/functions/v1') { throw 'Use the reviewed HTTPS portal functions URL.' }
    $ClaraBstr = [IntPtr]::Zero
    try {
        $ClaraBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Key)
        $ClaraPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ClaraBstr)
        if ($ClaraPlain -cnotmatch '^cw_[a-f0-9]{64}$') { throw 'The worker key has the wrong format. Copy it from Clara Settings.' }
    } finally {
        $ClaraPlain = $null
        if ($ClaraBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ClaraBstr) }
    }
    New-Item -ItemType Directory -Force -Path $DataFolder | Out-Null
    $ClaraConfigPath = Join-Path $DataFolder 'portal.json'
    $ClaraLock = $null
    $ClaraTemporary = Join-Path $DataFolder ('portal-' + [guid]::NewGuid().ToString('N') + '.tmp')
    $ClaraSecretPath = Join-Path $DataFolder ('portal-worker-' + [guid]::NewGuid().ToString('N') + '.dpapi')
    $ClaraCommitted = $false
    try {
        $ClaraLock = [IO.File]::Open((Join-Path $DataFolder 'instance.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try { $ClaraLock.Lock(0, 1) }
        catch { throw 'Clara is running. Stop its CLI with Ctrl+C before saving this connection.' }
        if (Test-Path -LiteralPath $ClaraConfigPath) {
            $ClaraExisting = Get-Content -LiteralPath $ClaraConfigPath -Raw | ConvertFrom-Json
            if ($ClaraExisting.protocol_version -ne 1 -or $ClaraExisting.worker_id -ne $ClaraId.ToString()) {
                throw 'This folder already has a different portal connection. Review it before replacing it.'
            }
            if ($ClaraExisting.base_url.TrimEnd('/') -ne $ClaraUrl.AbsoluteUri.TrimEnd('/')) {
                throw 'This folder is connected to a different portal URL. Review it before replacing it.'
            }
            if ($ClaraExisting.enabled) { throw 'Disable the existing portal connection and stop Clara before replacing its key.' }
        }
        $ClaraEncrypted = ConvertFrom-SecureString -SecureString $Key
        [IO.File]::WriteAllText($ClaraSecretPath, $ClaraEncrypted, (New-Object Text.UTF8Encoding($false)))
        $ClaraConfig = [ordered]@{
            enabled = $false; protocol_version = 1; base_url = $ClaraUrl.AbsoluteUri.TrimEnd('/')
            worker_id = $ClaraId.ToString(); token_env = 'CLARA_PORTAL_WORKER_KEY'
            credential_file = [IO.Path]::GetFileName($ClaraSecretPath)
            authentication_reviewed = $true
            windows_handoff = @{ exclusive_session = $true; qualified = $false }
        }
        [IO.File]::WriteAllText($ClaraTemporary, ($ClaraConfig | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
        # PowerShell 5.1 marshals ordinary $null to an empty string here.
        if (Test-Path -LiteralPath $ClaraConfigPath) { [IO.File]::Replace($ClaraTemporary, $ClaraConfigPath, [NullString]::Value) }
        else { [IO.File]::Move($ClaraTemporary, $ClaraConfigPath) }
        $ClaraCommitted = $true
    } finally {
        if ($ClaraLock) { $ClaraLock.Dispose() }
        if (Test-Path -LiteralPath $ClaraTemporary) { Remove-Item -LiteralPath $ClaraTemporary }
        if (-not $ClaraCommitted -and (Test-Path -LiteralPath $ClaraSecretPath)) { Remove-Item -LiteralPath $ClaraSecretPath }
    }
}

function Invoke-ClaraPortalProcess {
    param([string]$DataFolder, [string]$Python, [string[]]$Arguments)
    $ClaraPreviousKey = [Environment]::GetEnvironmentVariable('CLARA_PORTAL_WORKER_KEY', 'Process')
    $ClaraLoaded = $false
    try {
        $ClaraConfigPath = Join-Path $DataFolder 'portal.json'
        if (Test-Path -LiteralPath $ClaraConfigPath) {
            $ClaraConfig = Get-Content -LiteralPath $ClaraConfigPath -Raw | ConvertFrom-Json
            if ($ClaraConfig.enabled -and $ClaraConfig.protocol_version -eq 1 -and $ClaraConfig.credential_file) {
                if ($ClaraConfig.token_env -ne 'CLARA_PORTAL_WORKER_KEY' -or
                    $ClaraConfig.credential_file -cnotmatch '^portal-worker-[a-f0-9]{32}\.dpapi$') { throw 'Review the portal credential configuration.' }
                $ClaraBstr = [IntPtr]::Zero
                $ClaraSecureKey = $null
                try {
                    $ClaraProtectedKey = Get-Content -LiteralPath (Join-Path $DataFolder $ClaraConfig.credential_file) -Raw
                    $ClaraSecureKey = ConvertTo-SecureString -String $ClaraProtectedKey
                    $ClaraBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ClaraSecureKey)
                    $ClaraPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ClaraBstr)
                    if ($ClaraPlain -cnotmatch '^cw_[a-f0-9]{64}$') { throw 'Invalid saved worker key.' }
                    [Environment]::SetEnvironmentVariable('CLARA_PORTAL_WORKER_KEY', $ClaraPlain, 'Process')
                    $ClaraLoaded = $true
                } catch {
                    throw 'The saved worker key cannot be opened by this Windows account. Configure the connection again while Clara is stopped.'
                } finally {
                    $ClaraPlain = $null
                    if ($ClaraBstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ClaraBstr) }
                    if ($ClaraSecureKey) { $ClaraSecureKey.Dispose() }
                }
            }
        }
        & $Python @Arguments
        $script:ClaraProcessExitCode = $LASTEXITCODE
    } finally {
        if ($ClaraLoaded) { [Environment]::SetEnvironmentVariable('CLARA_PORTAL_WORKER_KEY', $ClaraPreviousKey, 'Process') }
        $ClaraPreviousKey = $null
    }
}
