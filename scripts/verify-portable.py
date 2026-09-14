"""Isolated startup and native-binary checks; no model inference or desktop actions."""
import asyncio
import importlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def probe_dashboard():
    # Use real runtime components and routes, without touching saved user data,
    # binding a port, starting a model task or connecting a tenant account.
    import httpx
    from clara import __version__
    from clara.app import create_app
    from clara.config import Config

    with tempfile.TemporaryDirectory(prefix="clara-startup-probe-") as folder:
        app = create_app(Config(Path(folder) / "data"), access_token="local-startup-probe")
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8876") as client:
                health = await client.get("/health")
                health.raise_for_status()
                if health.json() != {"status": "ok", "version": __version__}:
                    raise RuntimeError("Dashboard health check returned an unexpected result.")
                page = await client.get("/")
                page.raise_for_status()
                session = await client.post("/api/session", json={"token": "local-startup-probe"},
                                            headers={"x-clara-request": "1"})
                session.raise_for_status()
                for route in ("/api/settings", "/api/conversations"):
                    response = await client.get(route)
                    response.raise_for_status()
                if app.state.manager.active_job is not None or not app.state.manager.queue.empty():
                    raise RuntimeError("Startup probe unexpectedly queued a model task.")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"core", "desktop"}:
        raise SystemExit("Expected core or desktop.")
    if sys.argv[1] == "core":
        for name in ("ssl", "sqlite3", "ctypes", "clara.app", "pypdf", "docx", "pptx", "openpyxl"):
            importlib.import_module(name)
        # Loading the real wire contract also checks its optional format
        # validators. A disabled portal in the dashboard probe cannot do this.
        from clara.portal_contract import PortalContract
        PortalContract.bundled()
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(":memory:")) as probe:
            probe.execute("CREATE VIRTUAL TABLE clara_fts_probe USING fts5(text)")
        asyncio.run(probe_dashboard())
        from clara.auth import cli_path
        executable = cli_path()
        if not executable:
            raise SystemExit("The SDK's native Claude executable was not found.")
        subprocess.run([executable, "--version"], check=True, timeout=30)
        print("Core imports, portal contract, isolated dashboard startup and the native Claude executable passed.")
        print("No model task or desktop action was performed.")
    else:
        for name in ("win32api", "pythoncom", "comtypes", "dxcam", "windows_mcp.__main__"):
            importlib.import_module(name)
        subprocess.run([sys.executable, "-m", "windows_mcp", "serve", "--help"], check=True, timeout=30)
        subprocess.run([sys.executable, str(ROOT / "clara/windows_bridge.py"), "--probe"], check=True, timeout=30)
        print("Desktop imports and CLI help passed. No desktop action was performed.")


if __name__ == "__main__":
    main()
