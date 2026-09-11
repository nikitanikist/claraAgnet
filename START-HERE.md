# Your Clara build is ready for the next test

The real local app is in this folder. It includes chat, a Claude SDK executor, tools, skills, saved history, uploads/results, and Windows setup scripts. The existing Clearhouse portal and fixed T1 runner have not been modified.

**Windows milestone:** portable setup and native Claude login succeeded. The user's dashboard shows Clara creating, reading and publishing `clara-first-test.txt`, followed by a completed follow-up. Release 0.1.4 adds per-task token/cost reports, CSV export, an optional task estimate limit, direct-search guidance and an Explorer cleanup review. A fresh installation still needs native Claude login.

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

43 local Python tests pass. A real Chrome/API test verifies inline downloads, per-task usage, conversation totals, legacy records, CSV download, estimate-limit settings, streaming and mobile layout. The user reported a successful Softros Windows test; the new search/cleanup behaviors and tax workflows still need live Windows validation. This is an experimental build, not a completed production closeout system.

For RDP installation, use the GitHub instructions in **README.md**, or transfer **Clara-Agent-0.1.4.zip** to Windows and extract it to a persistent folder. If using the server's existing embeddable Python with no pip/venv, use **docs/PORTABLE-WINDOWS.md**. The package contains source/installers and downloads dependencies on the target machine. Your Mac virtual environment, local chat data and credentials are excluded.

Keep Chrome tools off while its connector is missing, and Windows desktop tools on for native application tests. Use a new conversation for each closeout so its usage total includes only that closeout and its follow-ups. The browser connector remains pending on the current server because Node.js was not found during setup.

After each task, expand **Token breakdown & models** beneath the reply. Use **Download usage CSV** in the side panel to export the conversation’s tasks. In **Connections & settings**, an optional **Task estimate limit (USD)** can stop long runs based on the SDK estimate. It may be exceeded by the last model step and is not a cap on Max subscription usage.
