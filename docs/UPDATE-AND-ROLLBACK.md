# Update and restore

Stop Clara with Ctrl+C in its PowerShell window before updating. Use the firm's approved script execution method. No administrator installation or policy change is performed.

For an existing Git install receiving this release for the first time:

```powershell
Set-Location "$env:LOCALAPPDATA\ClaraAgent"
git status --short
git pull --ff-only origin main
if ($LASTEXITCODE -eq 0) { .\Update-Clara.ps1 }
```

If `git status` shows local source edits, preserve them before pulling. The initial pull installs the new updater; its subsequent backup occurs before opening/upgrading the database. Later updates can start directly with `Update-Clara.ps1`, which backs up before pulling. Keep the previous Git revision from `git rev-parse HEAD` when performing the initial pull.

The updater creates a consistent local backup under `%LOCALAPPDATA%\ClaraBackups`, refreshes portable dependencies, installs Node/Chrome connector inside the app directory, probes native dependencies, and leaves application startup to you. Original client files and the old automation project are not updated. Browser and Claude credentials are excluded from the backup; workspace files, skills, attachments, artifacts, screenshot evidence, settings and a SQLite snapshot are included. Backups contain client material and stay local.

Run `Start-Clara.ps1`. In Connections, enable Chrome and Windows tools and add the approved test roots. Chrome is a dedicated profile; sign into the needed websites there. Use `Setup-Browser.ps1` to repair only the browser dependencies.

To roll back, stop Clara and use a clean checkout of the previous recorded source revision in a separate application folder. Provision its dependencies using that revision's installer and the existing approved Python runtime. Do not reset over local edits. For data restoration, first move the current `%LOCALAPPDATA%\Clara` folder aside, then run the new backup utility with `--restore` pointing to the selected backup ZIP. Restore requires the original data path and refuses an existing destination, because stored artifacts use absolute paths:

```powershell
& .\.portable-python\python.exe .\scripts\backup-data.py --restore "$env:LOCALAPPDATA\ClaraBackups\YOUR-BACKUP.zip"
```

Do not restore while Clara runs. Retain the moved data until conversations, downloads, skills and settings are checked. The restore does not undo remote uploads, sent messages or filed returns; inspect remote records before retrying business actions.
