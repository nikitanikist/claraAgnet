# Your Clara build is ready for the next test

The real local app is in this folder. It includes chat, a Claude SDK executor, tools, skills, saved history, uploads/results, and Windows setup scripts. The existing Clearhouse portal and fixed T1 runner have not been modified.

**Windows milestone:** portable setup and native Claude login succeeded. The user's dashboard shows Clara creating, reading and publishing `clara-first-test.txt`, followed by a completed follow-up. Release 0.1.3 displays downloads directly beneath the task in chat, including for saved conversations. A fresh installation still needs native Claude login.

To update the existing GitHub installation on RDP, stop Clara with Ctrl+C in its server terminal, then run:

```powershell
git -C "$env:LOCALAPPDATA\ClaraAgent" pull --ff-only
if ($LASTEXITCODE -eq 0) { & "$env:LOCALAPPDATA\ClaraAgent\Start-Clara.ps1" }
```

Refresh the dashboard and reopen the previous conversation. This update requires no dependency reinstall or repeated model task.

On this Mac:

1. Open **Login-Clara.command** and complete the official sign-in.
2. Open **Start-Clara.command**. If the app is already running, use **Open-Clara.command**.
3. Try: “Use the find-client-document skill. Find the synthetic Rohit Sharma engagement letter under clara-smoke in your workspace, verify its reference, and attach it.”
4. Then try: “Create a short Word document explaining the capabilities available on this computer. Attach the result.” Approve the document-generation command, or select autonomous mode for that task.
5. Review **Skills library** and **Connections & settings**.

30 local Python tests passed, including seven checks for the existing-runtime installer and dependency updates. A real Chrome/API test also verifies inline file downloads, history replay, task association, streaming, deduplication and mobile layout. Live browser actions and Windows desktop/TaxPrep behavior still need validation. This is an experimental build, not a completed production closeout system.

For RDP installation, use the GitHub instructions in **README.md**, or transfer **Clara-Agent-0.1.3.zip** to Windows and extract it to a persistent folder. If using the server's existing embeddable Python with no pip/venv, use **docs/PORTABLE-WINDOWS.md**. The package contains source/installers and downloads dependencies on the target machine. Your Mac virtual environment, local chat data and credentials are excluded.

Next, enable the installed Windows desktop connector and complete a harmless desktop task before testing the firm's tax workflow. The browser connector remains pending on the current server because Node.js was not found during setup.
