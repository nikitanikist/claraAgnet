import os
import shutil
import sys
from pathlib import Path
from .config import PROJECT


def desktop_command():
    portable = PROJECT / ".portable-desktop/python.exe"
    if portable.is_file() and (portable.parent / ".clara-ready").is_file():
        return str(portable), ["-m", "windows_mcp"]
    regular = PROJECT / ".windows-venv/Scripts/windows-mcp.exe"
    if regular.is_file():
        return str(regular), []
    return None


def connector_status(config):
    node = shutil.which("node")
    browser = PROJECT / "node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"
    desktop = desktop_command()
    return {"browser": {"installed": bool(node and browser.exists()), "enabled": config.settings()["browser_enabled"],
                        "message": "Uses a separate Clara Chrome profile. Sign into websites there when needed."},
            "desktop": {"installed": os.name == "nt" and bool(desktop), "enabled": config.settings()["desktop_enabled"],
                        "supported_platform": os.name == "nt", "message": "Requires a usable Windows interactive desktop. RDP and TaxPrep validation are pending."}}


def mcp_connectors(config):
    settings = config.settings()
    status = connector_status(config)
    servers = {}
    if settings["browser_enabled"]:
        if not status["browser"]["installed"]:
            raise ValueError("Browser connector missing. Run npm ci in the Clara application folder.")
        servers["chrome"] = {"type": "stdio", "command": shutil.which("node"), "args": [
            str(PROJECT / "node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"),
            "--user-data-dir=" + str(config.data / "chrome-profile"), "--no-usage-statistics",
            "--no-performance-crux", "--no-category-performance", "--no-category-emulation",
            "--redact-network-headers", "--workspace=" + str(config.workspace),
            "--screenshot-format=jpeg", "--screenshot-max-width=1440"],
            "env": {"CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS": "1"}}
    if settings["desktop_enabled"]:
        if not status["desktop"]["installed"]:
            raise ValueError("Windows desktop connector unavailable. Complete desktop setup on Windows, or disable Desktop in Settings.")
        command, prefix = desktop_command()
        servers["windows"] = {"type": "stdio", "command": command,
                              "args": prefix + ["serve", "--exclude-tools=PowerShell,Registry,FileSystem,Process"],
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
