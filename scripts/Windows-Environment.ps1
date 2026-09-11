# Shared by the Windows launchers; changes only the current process environment.
function Initialize-ClaraWindows {
    param([string]$Root)
    $ClaraPython = Join-Path $Root '.portable-python\python.exe'
    if (-not (Test-Path (Join-Path $Root '.portable-python\.clara-ready'))) {
        $ClaraPython = Join-Path $Root '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path $ClaraPython)) {
        throw 'Complete the standard or portable Clara installer first.'
    }
    $env:Path = "$(Split-Path -Parent $ClaraPython);$env:Path"
    $env:PYTHONIOENCODING = 'utf-8'
    if (-not $env:CLAUDE_CODE_GIT_BASH_PATH) {
        $ClaraGitCandidates = @("$env:ProgramFiles\Git\bin\bash.exe", "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe")
        $ClaraGitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
        if ($ClaraGitCommand) {
            $ClaraGitCandidates += Join-Path (Split-Path -Parent (Split-Path -Parent $ClaraGitCommand.Source)) 'bin\bash.exe'
        }
        foreach ($ClaraGit in $ClaraGitCandidates) {
            if (Test-Path $ClaraGit) { $env:CLAUDE_CODE_GIT_BASH_PATH = $ClaraGit; break }
        }
    }
    return $ClaraPython
}
