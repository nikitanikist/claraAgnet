# Clone/update Clara and use a working, existing embeddable Python runtime.
# Run using your normal approved PowerShell script execution method.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'ClaraAgent'),
    [switch]$SkipDesktop,
    [switch]$SkipBrowser
)
$ErrorActionPreference = 'Stop'
$ClaraRepository = 'https://github.com/nikitanikist/claraAgnet.git'
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'The specified existing python.exe was not found.' }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw 'Git for Windows is required to clone Clara.' }

function Invoke-ClaraGit {
    param([string[]]$GitArguments)
    & git.exe @GitArguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed with exit code $LASTEXITCODE. Setup stopped." }
}

if (Test-Path -LiteralPath $InstallDir) {
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDir '.git'))) {
        throw 'The destination already exists and is not a Git checkout. Choose a new -InstallDir.'
    }
    $ClaraOrigin = (Invoke-ClaraGit @('-C', $InstallDir, 'remote', 'get-url', 'origin')).Trim()
    if ($ClaraOrigin -notin @($ClaraRepository, 'https://github.com/nikitanikist/claraAgnet')) {
        throw 'The existing checkout belongs to another repository. Choose a new -InstallDir.'
    }
    $ClaraChanges = Invoke-ClaraGit @('-C', $InstallDir, 'status', '--porcelain')
    if ($ClaraChanges) { throw 'The checkout has local edits. Save them before updating Clara.' }
    $ClaraBranch = (Invoke-ClaraGit @('-C', $InstallDir, 'branch', '--show-current')).Trim()
    if ($ClaraBranch -ne 'main') { throw 'This checkout is not on main. Choose a new -InstallDir.' }
    Invoke-ClaraGit @('-C', $InstallDir, 'pull', '--ff-only', 'origin', 'main')
} else {
    Invoke-ClaraGit @('clone', '--branch', 'main', $ClaraRepository, $InstallDir)
}

$ClaraArguments = @((Join-Path $InstallDir 'scripts\install-portable.py'))
if ($SkipDesktop) { $ClaraArguments += '--skip-desktop' }
if ($SkipBrowser) { $ClaraArguments += '--skip-browser' }
& $PythonPath @ClaraArguments
if ($LASTEXITCODE -ne 0) { throw "Clara setup stopped with exit code $LASTEXITCODE. Keep the output for diagnosis." }
Write-Host "Clara folder: $InstallDir" -ForegroundColor Green
Write-Host "Next: run Login-Clara.ps1, then Start-Clara.ps1 from that folder."
