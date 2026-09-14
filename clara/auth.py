"""Uses the unmodified, officially installed CLI and its native sign-in."""
import asyncio
import json
import os
import shutil
from pathlib import Path


# Captured only from this process's explicitly configured environment. These
# values are never copied into SDK/tool subprocesses, records or diagnostics.
_portal_credentials = {}


def portal_credential(name):
    if not isinstance(name, str) or not name.startswith('CLARA_PORTAL_'):
        raise ValueError('Use an explicitly configured CLARA_PORTAL_ credential name.')
    sanitize_process_environment()
    return _portal_credentials.get(name)


def private_environment(key):
    return billing_override(key) or key.startswith('CLARA_PORTAL_')


def billing_override(key):
    return (key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_", "AWS_", "AZURE_", "GOOGLE_"))
            or key in {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_API_KEY_HELPER", "CLAUDE_CONFIG_DIR", "CLAUDECODE"})


def clean_environment(source=None):
    return {k: v for k, v in (source if source is not None else os.environ).items() if not private_environment(k)}


def sanitize_process_environment():
    # SDK subprocesses inherit their parent's environment. Keep portal credentials
    # in this service only; remove billing overrides. The user's shell is unchanged.
    for key in list(os.environ):
        if key.startswith('CLARA_PORTAL_'):
            _portal_credentials[key] = os.environ.pop(key)
        elif billing_override(key):
            os.environ.pop(key)


def cli_path():
    # Keep the CLI protocol matched to the pinned SDK. It uses the official
    # account's native sign-in, without copying or parsing its credentials.
    import claude_agent_sdk
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / ("claude.exe" if os.name == "nt" else "claude")
    if bundled.is_file():
        return str(bundled)
    candidates = [Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")]
    located = shutil.which("claude")
    if located:
        candidates.append(Path(located))
    for path in candidates:
        if path.is_file() and path.suffix.lower() not in {".cmd", ".bat"}:
            return str(path)
    return None


async def auth_status(config=None):
    executable = cli_path()
    if not executable:
        return {"connected": False, "message": "Claude Code is missing. Run the installer, then clara login."}
    process = await asyncio.create_subprocess_exec(executable, "auth", "status", "--json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=clean_environment())
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 15)
        result = json.loads(stdout)
    except (TimeoutError, ValueError):
        if process.returncode is None:
            process.kill()
            await process.wait()
        return {"connected": False, "message": "Could not confirm native Claude sign-in. Run clara login."}
    connected = (result.get("loggedIn") is True and result.get("authMethod") == "claude.ai"
                 and result.get("apiProvider") in {None, "firstParty"}
                 and result.get("subscriptionType") in {"max", "pro", "team", "enterprise"})
    health_file = config.data / "model-health.json" if config else None
    health = json.loads(health_file.read_text()) if health_file and health_file.exists() else {}
    needs_login = bool(health.get("needs_login"))
    return {"connected": connected, "auth_method": result.get("authMethod"),
            "plan": result.get("subscriptionType"), "api_fallback": False,
            "inference_verified": health.get("inference_verified", False), "needs_login": needs_login,
            "message": ("The last model call could not authenticate. Run clara login in a terminal, then retry."
                        if needs_login else "Native subscription sign-in found. A live task verifies that the session is usable."
                        if connected else "Subscription sign-in required. Run clara login in a terminal. No API billing fallback is configured.")}
