import argparse
import asyncio
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from .auth import auth_status, cli_path, clean_environment, sanitize_process_environment
from .config import Config, default_data
from .connectors import connector_status, desktop_ready


def main():
    parser = argparse.ArgumentParser(description="Clara — local computer assistant")
    parser.add_argument("command", choices=["serve", "doctor", "login", "open"], nargs="?", default="serve")
    parser.add_argument("--data-dir", type=Path, default=default_data())
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535")
    config = Config(args.data_dir, args.port)
    for item in config.initialize():
        print(f"Starter skill '{item['skill']}' has a packaged update that was not applied ({item['reason']}): "
              f"installed {item['installed_sha256'] or 'missing'} vs packaged {item['packaged_sha256']}. "
              "See skills-update-pending.json in the data folder.", file=sys.stderr)
    if args.command == "login":
        executable = cli_path()
        if not executable:
            raise SystemExit("Claude Code is missing. Run the installer first.")
        result = subprocess.call([executable, "auth", "login"], env=clean_environment())
        if result == 0:
            (config.data / "model-health.json").unlink(missing_ok=True)
        raise SystemExit(result)
    if args.command == "doctor":
        print(json.dumps({"auth": asyncio.run(auth_status(config)), "connectors": connector_status(config),
                          "desktop": desktop_ready(), "workspace": str(config.workspace)}, indent=2))
        return
    if args.command == "open":
        file = config.data / "dashboard.json"
        if not file.exists():
            raise SystemExit("Start Clara first with: clara serve")
        webbrowser.open(json.loads(file.read_text())["url"])
        return
    sanitize_process_environment()
    import uvicorn
    from .app import create_app
    from .instance import single_instance
    with single_instance(config.data):
        app = create_app(config)
        if not args.no_open:
            import threading
            threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{config.port}/#access={app.state.access_token}")).start()
        print(f"Clara dashboard: http://127.0.0.1:{config.port} — use 'clara open' to connect another browser.")
        uvicorn.run(app, host="127.0.0.1", port=config.port, access_log=False)


if __name__ == "__main__":
    main()
