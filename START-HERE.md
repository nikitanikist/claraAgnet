# Your Clara build is ready for the next test

The real local app is in this folder. It includes chat, a Claude SDK executor, tools, skills, saved history, uploads/results, and Windows setup scripts. The existing Clearhouse portal and fixed T1 runner have not been modified.

**First action: sign in to Claude.** The stored login used by the older CLI could not authenticate, and the SDK's matching bundled CLI needs its native login. Until that is done, Clara's model tasks will fail honestly rather than use an API key.

On this Mac:

1. Open **Login-Clara.command** and complete the official sign-in.
2. Open **Start-Clara.command**. If the app is already running, use **Open-Clara.command**.
3. Try: “Use the find-client-document skill. Find the synthetic Rohit Sharma engagement letter under clara-smoke in your workspace, verify its reference, and attach it.”
4. Then try: “Create a short Word document explaining the capabilities available on this computer. Attach the result.” Approve the document-generation command, or select autonomous mode for that task.
5. Review **Skills library** and **Connections & settings**.

30 local tests passed, including seven checks for the existing-runtime installer and dependency updates. Real model completion, browser actions and Windows/TaxPrep behavior still need validation. This is an experimental build, not a completed production closeout system.

For RDP installation, use the GitHub instructions in **README.md**, or transfer **Clara-Agent-0.1.2.zip** to Windows and extract it to a persistent folder. If using the server's existing embeddable Python with no pip/venv, use **docs/PORTABLE-WINDOWS.md**. The package contains source/installers and downloads dependencies on the target machine. Your Mac virtual environment, local chat data and credentials are excluded.

When you return, connect Claude first. Then we can run the live prototype and make the existing portal integration concrete before the Windows workflow test.
