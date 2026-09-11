"""Import and native-binary checks; no model inference or desktop actions."""
import importlib
import subprocess
import sys

if sys.argv[1] == "core":
    for name in ("ssl", "sqlite3", "ctypes", "clara.app", "pypdf", "docx", "pptx", "openpyxl"):
        importlib.import_module(name)
    from clara.auth import cli_path
    executable = cli_path()
    if not executable:
        raise SystemExit("The SDK's native Claude executable was not found.")
    subprocess.run([executable, "--version"], check=True, timeout=30)
    print("Core imports and the native Claude executable passed.")
elif sys.argv[1] == "desktop":
    for name in ("win32api", "pythoncom", "comtypes", "dxcam", "windows_mcp.__main__"):
        importlib.import_module(name)
    subprocess.run([sys.executable, "-m", "windows_mcp", "serve", "--help"], check=True, timeout=30)
    print("Desktop imports and CLI help passed. No desktop action was performed.")
else:
    raise SystemExit("Expected core or desktop.")
