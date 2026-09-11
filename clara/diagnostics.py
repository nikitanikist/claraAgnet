"""Bounded text diagnostics. Screenshot evidence is stored separately; this module never executes a recovery."""
import json
import re


def redact_text(text):
    text=re.sub(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+',r'\1[redacted]',text)
    text=re.sub(r'sk-ant-[A-Za-z0-9_-]{10,}','[redacted]',text)
    return re.sub(r'''(?i)(["']?(?:password|api_key|access_token|refresh_token|client_secret)["']?\s*[:=]\s*)["'][^"']*["']''',r'\1"[redacted]"',text)


def usable_snapshot(name, args):
    """Windows-MCP defaults vision off, so disabling its tree can observe nothing."""
    enabled = lambda value: value is True or isinstance(value, str) and value.lower() == "true"
    if (name == "mcp__windows__Snapshot" and not enabled(args.get("use_ui_tree", True))
            and not enabled(args.get("use_vision", False))):
        return {**args, "use_vision": True}
    return args


def tool_diagnostic(data, duration_ms=None):
    """Keep text evidence and explicit error signals, not a claim of UI success."""
    texts, images, structured_error = [], 0, False

    def collect(value):
        nonlocal images, structured_error
        if isinstance(value, dict):
            if value.get("type") in {"image", "audio"}:
                images += value.get("type") == "image"
                return
            if value.get("isError") is True or value.get("is_error") is True:
                structured_error = True
            if value.get('clara_observation') and value.get('verified') is False:
                structured_error = True
            if isinstance(value.get("exit_code"), int) and value["exit_code"] != 0:
                structured_error = True
            if value.get("type") == "text" and isinstance(value.get("text"), str):
                collect(value["text"])
            elif "content" in value:
                collect(value["content"])
            else:
                texts.append(json.dumps(value, ensure_ascii=False, default=str))
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                decoded = None
            if isinstance(decoded, (dict, list)):
                collect(decoded)
            else:
                texts.append(value)
        elif value is not None:
            texts.append(str(value))

    collect(data.get("tool_response", data.get("error")))
    text = "\n".join(texts)
    # Windows-MCP can return a plain error string with MCP success.
    connector_error = data.get("tool_name", "").startswith("mcp__windows__") and bool(
        re.match(r"^(?:Error (?:switching app|capturing|clicking|typing)\b|"
                 r"Failed to get desktop state\b|No windows found on the desktop\b|"
                 r"Application .+ not found\.)", text.strip(), re.I))
    # Basic credential masking; arbitrary client text is not anonymized.
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", text)
    text = re.sub(r"sk-ant-[A-Za-z0-9_-]{10,}", "[redacted]", text)
    text = re.sub(r'(?i)([\"\']?(?:password|api_key|access_token|refresh_token|client_secret)[\"\']?\s*[:=]\s*)[\"\'][^\"\']*[\"\']',
                  r'\1"[redacted]"', text)
    length = len(text)
    if length > 6000:
        text = text[:4500] + "\n[Middle omitted from saved diagnostic]\n" + text[-1500:]
    return {"failed": bool(data.get("hook_event_name") == "PostToolUseFailure" or structured_error or connector_error),
            "duration_ms": duration_ms, "output_excerpt": text,
            "output_chars": length, "output_truncated": length > 6000, "image_count": images,
            "note": "Tool return evidence only; task completion requires verification. Image bytes are excluded from this text record."}


def limit_message(result, max_turns, last_tool):
    if result.subtype == "error_max_turns":
        last = f" Last tool requested: {last_tool}." if last_tool else ""
        return (f"Clara stopped at the configured {max_turns}-turn limit; the task is incomplete.{last} "
                "Completed actions were not undone. Review the activity and any saved checkpoint before "
                "resuming in this conversation; do not restart document creation blindly.")
    return (result.result or "; ".join(result.errors or []) or result.subtype)[:3000]
