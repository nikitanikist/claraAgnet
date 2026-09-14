# Windows connection for controlled portal testing

Use the existing dedicated Clara Windows account. This is an integration test installation; it does not qualify the RDP or enable general staff execution.

1. Stop the idle Clara CLI with Ctrl+C. The read-only diagnostic can run alongside Clara, but updating source and configuring credentials require it stopped.
2. Run `Update-ClaraPortalTest.ps1` with an explicitly reviewed full commit SHA from `feat/clearhouse-portal-v1`. The script may be downloaded outside the application folder. It checks the Git origin and clean source, fetches that branch, backs up the existing data, holds the instance lock, selects the exact revision and refreshes dependencies. It retains the prior revision and backup path in a dated local update record. It never starts or enables Clara. `Update-Clara.ps1` is the regular main-branch updater and does not install this integration test.
3. Run `Connect-ClaraPortal.ps1 -WorkerId <issued UUID> -FunctionsUrl <reviewed HTTPS functions URL>`. Enter the issued worker key only at its hidden prompt. Keep the existing portal runner; this command does not enroll another runner or contact the server.
4. The connection is saved in `%LOCALAPPDATA%\Clara\portal.json` with execution disabled and Windows handoff unqualified. The key is in a separate Windows DPAPI file encrypted for this Windows account. Plaintext is not written to the config, command history or output. Normal Clara backups exclude both the portal config and DPAPI credential. Reconfigure the worker after moving to a different Windows account/machine.
5. During a subsequent controlled connection test, enable the reviewed local connection and restart `Start-Clara.ps1`. It decrypts the key just for the Clara service; Python removes it from the environment inherited by model and command subprocesses. The parent PowerShell environment is restored after Clara exits. This is credential handling, not a sandbox against programs running as the same Windows account.
6. Keep portal execution off until test assignments and provider access are ready. Complete the connected acceptance in WINDOWS-WORKER-HANDOFF.md before general release. Laureen handles invoicing and email.

If the portal key was not retained when issued, rotate the key on that same runner in Clara Settings and use the new one. An enabled local connection must first be disabled and Clara stopped before reconfiguration. Existing encrypted key files are retained locally to avoid invalidating an earlier config during a failed save; they are not included in data backups.

The setup command records the already reviewed arrangement: one dedicated worker using that Windows account's native Claude sign-in. It does not copy model credentials, switch billing or verify live inference. A connected test must still verify authentication, browser sessions and software access.

For rollback after a test install, retain the local update record and backup. Follow UPDATE-AND-ROLLBACK.md with the recorded previous revision and reinstall its matching dependencies. Do not delete the current data or restore over it blindly.
