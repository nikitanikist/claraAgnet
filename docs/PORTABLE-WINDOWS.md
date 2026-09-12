# Setup using an existing Windows embeddable Python

Use this route when the server already has an approved, working 64-bit embeddable Python 3.12+ but has no pip, venv or ensurepip. The normal Clara installer requires a full Python distribution and is not suitable for this runtime. This is application packaging, not a change to Windows installer policy.

Clone the repository or extract Clara-Agent-0.2.3.zip into a new, persistent application folder belonging to the current user. A short path under LOCALAPPDATA is preferable to a deeply nested network folder. Keep the existing Clara application and Python folder in place.

Run the new installer with the existing interpreter, using actual paths on that server:

```powershell
& 'O:\path\to\existing\python.exe' 'C:\path\to\Clara-Agent\scripts\install-portable.py'
```

The script reads the existing runtime and creates `.portable-python` beside Clara's source. It copies only interpreter files, replaces stale Python search paths in the copy, and provisions the application's packages into that copy's `Lib/site-packages`. The original interpreter, dependencies and old application's files are not modified. The application source is loaded directly; no editable installation or virtual environment is required.

The package installer is pip 26.2.1, downloaded from its pinned PyPI wheel URL and verified against the published SHA-256. It runs as a setup helper, outside the application runtime. Packages come from PyPI as wheels; the installer will stop if a dependency needs an unavailable native build. It uses the existing runtime, not a new Python download. No administrator elevation, registry edits, policy changes or machine PATH changes are made.

The Windows desktop connector is provisioned in a separate `.portable-desktop` copy because its MCP dependencies differ from Clara's SDK dependencies. Setup checks pywin32/COM imports and the connector's CLI help and Clara bridge registration without taking screenshots or performing clicks. It writes readiness markers only after dependency and import checks pass. If desktop setup fails, the final report states this explicitly and the core remains available for diagnosis. `--skip-desktop` intentionally installs the core only.

Chrome's connector uses an existing compatible Node/npm when available, otherwise the Windows installer downloads the pinned Node 22.22.3 x64 archive from nodejs.org, verifies its SHA-256, and unpacks it into `.portable-node`. It uses locked npm dependencies without machine PATH changes or elevation. `--skip-browser` leaves setup pending; run Setup-Browser.ps1 later to repair it. Google Chrome must already be installed in a standard location.

After setup, run Login-Clara.ps1 and then Start-Clara.ps1 using the firm's normal approved script execution method. Both launchers recognize the portable copy, put its Python on the current process PATH, and find Git Bash for the native Claude CLI. Sign in with the intended person's account and verify a simple file task on each new installation.

The installer records `portable-setup-result.json`. A rerun verifies previously completed components and rebuilds dependency directories when their requirements change or setup was incomplete. These directories are owned by this installer. Stop the Clara process before rerunning setup. Keep the entire application folder in place after installation.

## Validation limits

Source-copy isolation, retry behavior, rejection of unrelated destinations, wheel checksum/path checks and connector selection are covered by automated tests on the development Mac. The target Windows interpreter is confirmed by the user's RDP output as Python 3.12.8, 64-bit. The user's subsequent screenshots confirm portable core and desktop installation, native imports and CLI help, and a live file create/read/publish task after Claude login. That earlier browser setup was pending because Node.js was absent. Version 0.2.0 adds local Node provisioning and a fresh Windows bridge. These new native paths require target-server acceptance; real Chrome MCP actions have passed on the Mac. RDP disconnect behavior and complete TaxPrep operation remain unverified.

Python describes application-local dependencies for its embeddable distribution in the [official Windows documentation](https://docs.python.org/3.12/using/windows.html#the-embeddable-package). The embedded runtime is not treated as a general-purpose pip installation; these packages belong to this Clara build.
