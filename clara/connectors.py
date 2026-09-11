import os
import shutil
import sys
from pathlib import Path
from .config import PROJECT


def node_command():
    portable = PROJECT / '.portable-node/node.exe'
    return str(portable) if os.name == 'nt' and portable.is_file() else shutil.which('node')


def chrome_command():
    candidates = ([os.path.join(os.environ.get(base, ''), suffix)
                   for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
                   for suffix in ('Google/Chrome/Application/chrome.exe',)] if os.name == 'nt' else
                  ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'])
    return next((str(p) for p in map(Path, candidates) if p.is_file()), None) or shutil.which('google-chrome')


def desktop_command():
    portable = PROJECT / ".portable-desktop/python.exe"
    if portable.is_file() and (portable.parent / ".clara-ready").is_file():
        return str(portable), [str(PROJECT / 'clara/windows_bridge.py')]
    regular = PROJECT / ".windows-venv/Scripts/python.exe"
    if regular.is_file():
        return str(regular), [str(PROJECT / 'clara/windows_bridge.py')]
    return None


def connector_status(config):
    node = node_command()
    browser = PROJECT / "node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"
    desktop = desktop_command()
    browser_installed = bool(node and browser.exists())
    return {"browser": {"installed": browser_installed, "enabled": config.settings()["browser_enabled"],
                        "available": bool(browser_installed and chrome_command()),
                        "chrome_found": bool(chrome_command()),
                        "message": ("Run Setup-Browser.ps1 in the Clara application folder. No administrator installation is required." if not browser_installed else
                                    "Google Chrome was not found in a standard installation location." if not chrome_command() else
                                    "Uses a separate Clara Chrome profile. Sign into websites there when needed.")},
            "desktop": {"installed": os.name == "nt" and bool(desktop), "enabled": config.settings()["desktop_enabled"],
                        "supported_platform": os.name == "nt", "message": "Requires a usable Windows interactive desktop. RDP and TaxPrep validation are pending."}}


def mcp_connectors(config):
    settings = config.settings()
    status = connector_status(config)
    servers = {}
    if settings["browser_enabled"] and status["browser"]["available"]:
        servers["chrome"] = {"type": "stdio", "command": node_command(), "args": [
            str(PROJECT / "node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"),
            "--user-data-dir=" + str(config.data / "chrome-profile"), "--no-usage-statistics",
            "--no-performance-crux", "--no-category-performance", "--no-category-emulation",
            "--redact-network-headers", "--workspace=" + str(config.workspace),
            "--screenshot-format=jpeg", "--screenshot-max-width=1440"],
            "env": {"CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1"}}
        if chrome_command():
            servers['chrome']['args'].append('--executable-path=' + chrome_command())
    if settings["desktop_enabled"]:
        if not status["desktop"]["installed"] or not desktop_ready()['ready']:
            return servers
        command, prefix = desktop_command()
        servers["windows"] = {"type": "stdio", "command": command,
                              "args": prefix,
                              "env": {"ANONYMIZED_TELEMETRY": "false", "PYTHONIOENCODING": "utf-8"}}
    return servers


def desktop_ready():
    if os.name != "nt":
        return {"ready": False, "message": "Native desktop tools are for Windows; files, commands and browser tools work on Mac."}
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    handle = user32.OpenInputDesktop(0, False, 0x0100)
    if not handle:
        return {"ready": False, "message": "Input desktop unavailable. Sign into the Windows session and unlock it."}
    user32.CloseDesktop(handle)
    return {"ready": True, "message": "Input desktop is accessible. A screenshot and harmless UI action still need testing."}
