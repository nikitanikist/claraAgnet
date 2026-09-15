# Automatic Windows startup

Run once in the dedicated Clara Windows account after connecting the worker:

```powershell
& "$env:LOCALAPPDATA\ClaraAgent\Set-ClaraAutostart.ps1" -Start
```

This installs a per-account Windows Task Scheduler task. It starts Clara at
Windows sign-in, keeps the process running in the interactive desktop, and retries
within about one minute after an exit. It uses the existing encrypted worker key
and model sign-in. No password is put in the scheduled task. It does not reopen
the local dashboard or restart completed/interrupted workflows.

One scheduled instance is allowed. Clara's existing OS lock also prevents a
second copy if someone has already started it manually. Closing the browser does
not stop the worker. An idle application window is not a second Clara instance.

A per-user Startup shortcut runs the same registration at sign-in, so a roaming
profile can register on the next RDP host. No RDP/computer name is hard-coded.
The application, data, encrypted credentials and Startup folder must be available
in that account's profile on the host; this does not install software onto an
unprepared server or create additional workers.

Windows must be signed in and unlocked for desktop operations. Signing into the
web portal cannot power on a server, sign into Windows, or unlock its desktop.
Disconnected/locked desktop behavior must be checked for the firm's RDP setup.

Before an update, pause automatic restart:

```powershell
& "$env:LOCALAPPDATA\ClaraAgent\Set-ClaraAutostart.ps1" -Disable
```

This pauses startup without terminating current work. Wait for the current task
to finish. Stop the idle scheduled task in Task Scheduler (the script prints its
name), or use Ctrl+C if Clara was started manually, then run the update. Re-enable
with `Set-ClaraAutostart.ps1 -Start` afterward. A persistent pause file also stops
the minute trigger from restarting Clara during maintenance.

Local startup output is kept in `%LOCALAPPDATA%\Clara\logs\automatic-start.log`.
It is rotated on startup when larger than 5 MB. Logs stay on the Windows account;
they are not copied into the portal or sent to the model.
