# First Windows/RDP acceptance session

This checklist is intended for the actual Windows server after installation. None of the native Windows checks below has passed on the Mac.

Use an isolated synthetic workspace and the intended Windows user account. Keep a copy of the run's conversation and artifacts as evidence.

| Check | Action | Evidence required |
|---|---|---|
| Installation | Run installer, then `.venv\Scripts\python.exe -m clara doctor` | Python/dependencies healthy, native Claude available, expected connectors installed |
| Login | Run `Login-Clara.ps1`, complete the official flow, run a short task | Live assistant response; a stored-login label alone is insufficient |
| Document discovery | Place synthetic engagement letters under nested/moved folders; include similar surnames | Correct document found and its contents checked before attachment |
| Ambiguity | Provide two plausible versions with no year in the request | Clara asks for the missing detail |
| Document creation | Request a Word document or short presentation | Real file opens in Office; content and formatting are checked |
| Chrome | Enable browser tools; ask for a harmless task on a test webpage | MCP connects, live snapshot is read, action produces the expected page state |
| Website session | Open the relevant service in Clara's dedicated Chrome profile | Intended account signed in; no cookie copying from another browser |
| Desktop | Enable desktop tools; open Notepad and enter a synthetic sentence | Correct Windows session and application controlled |
| Popups | Trigger a harmless test dialog | Clara reads the popup, chooses a valid action and verifies the next state |
| Stop | Stop a long test command and a pending approval | Job becomes cancelled and child command stops; next queued task proceeds |
| Restart | Stop the server during a harmless task and restart | Interrupted status; no automatic task replay |
| RDP locked | Lock the Windows session during a harmless test | Clear failure/wait; no claim of continued GUI success |
| RDP disconnected | Disconnect and reconnect during a harmless test | Document actual behavior on this server; do not assume desktop availability |
| TaxPrep/Profile | Use a test return and a provided SOP to export to a working folder | Client/year/source copy correct, export structurally and visually checked |
| Downstream draft | Use a test recipient/template/account for document preparation | No duplicates; destination confirmation and document ID recorded |
| Complete closeout | Execute a representative synthetic closeout with review | Every required output and workflow step verified against the firm's checklist |

Do not call the agent production-ready based only on a successful demo. Measure repeatability across changed file paths, unfamiliar dialogs, missing inputs, partial success and service timeouts. The intended first milestone is a useful supervised agent; broader autonomy follows observed results.

Windows-MCP's upstream support list names Windows desktop editions and does not explicitly certify this firm's Windows Server configuration. The installer and basic desktop checks establish compatibility only when executed there.

Sources: [Windows-MCP](https://github.com/CursorTouch/Windows-MCP), [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp).
