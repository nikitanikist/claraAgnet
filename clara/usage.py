"""Per-query SDK usage, kept separate from subscription billing and allowance."""
import csv
import io
import json
import math
from datetime import datetime, timezone

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
MODEL_KEYS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
NOTE = "SDK API cost estimate in USD, not a Max bill or remaining allowance. Different token categories have different rates."
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "incomplete", "needs_review"}


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def token_counts(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {key: number(raw.get(key, 0 if key.startswith("cache_") else None)) for key in TOKEN_KEYS}


def total(tokens):
    return sum(tokens.values()) if all(value is not None for value in tokens.values()) else None


def normalize_usage(raw):
    """Read both old saved usage and new results without inventing missing totals."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            raw = None
    raw = raw if isinstance(raw, dict) else {}
    if raw.get("version") == 2:
        return raw
    tokens = token_counts(raw.get("tokens"))
    cost = number(raw.get("sdk_estimated_usd"))
    available = total(tokens) is not None
    return {"version": 2, "tokens": tokens, "total_tokens": total(tokens),
            "sdk_estimated_usd": cost, "models": [], "scope": "main_loop",
            "coverage": "reported" if available else "unavailable", "note": NOTE,
            "turns": number(raw.get("turns")), "duration_ms": number(raw.get("duration_ms")),
            "wall_duration_ms": number(raw.get("wall_duration_ms")),
            "user_wait_ms": number(raw.get("user_wait_ms")),
            "active_duration_ms": number(raw.get("active_duration_ms")),
            "limit_usd": number(raw.get("limit_usd"))}


def with_wait_timing(store, job, report, ended_at):
    """Union recorded input waits; processing time is elapsed time, not inference time."""
    wall = number(report.get('wall_duration_ms'))
    if wall is None:
        return report
    start = ended_at - wall / 1000
    pending = {}; intervals = []
    rows = store.rows("SELECT kind,data,created FROM events WHERE job_id=? AND kind IN ('question','approval','answer') ORDER BY id", (job['id'],))
    for row in rows:
        data = json.loads(row['data']); rid = data.get('request_id')
        if not rid:
            continue
        if row['kind'] in {'question', 'approval'}:
            pending.setdefault(rid, row['created'])
        elif rid in pending:
            intervals.append((pending.pop(rid), row['created']))
    intervals.extend((value, ended_at) for value in pending.values())
    wait = 0; previous_end = start
    for left, right in sorted(intervals):
        left = max(start, previous_end, left); right = min(ended_at, right)
        if right > left:
            wait += right - left; previous_end = right
    wait_ms = min(wall, round(wait * 1000))
    return {**report, 'user_wait_ms': wait_ms, 'active_duration_ms': wall - wait_ms}


class UsageTracker:
    def __init__(self):
        self.steps = {}

    def observe(self, message):
        # Parallel tool blocks may repeat the same message ID. Output counts on
        # AssistantMessage are placeholders, not final generated token totals.
        if message.message_id and message.usage and not message.parent_tool_use_id:
            counts = token_counts(message.usage)
            counts["output_tokens"] = None
            self.steps[message.message_id] = counts

    def partial(self, duration_ms, limit_usd=None):
        tokens = {key: None for key in TOKEN_KEYS}
        if self.steps:
            for key in TOKEN_KEYS:
                values = [step[key] for step in self.steps.values()]
                if all(value is not None for value in values):
                    tokens[key] = sum(values)
        return {"version": 2, "tokens": tokens, "total_tokens": None,
                "sdk_estimated_usd": None, "models": [], "scope": "main_loop",
                "coverage": "partial" if self.steps else "unavailable", "note": NOTE,
                "turns": None, "duration_ms": None, "wall_duration_ms": duration_ms,
                "limit_usd": limit_usd}

    def result(self, message, duration_ms, limit_usd=None):
        models = []
        for name, values in (message.model_usage or {}).items():
            tokens = token_counts({key: values.get(model_key) for key, model_key in zip(TOKEN_KEYS, MODEL_KEYS)})
            models.append({"model": name, "tokens": tokens, "total_tokens": total(tokens),
                           "sdk_estimated_usd": number(values.get("costUSD")),
                           "cost_basis": values.get("costBasis", "sdk_price_table")})
        tokens = token_counts(message.usage)
        scope = "main_loop"
        if models:
            tokens = {key: sum(m["tokens"][key] for m in models)
                      if all(m["tokens"][key] is not None for m in models) else None for key in TOKEN_KEYS}
            scope = "all_models"
        cost = number(message.total_cost_usd)
        if cost is None and models and all(m["sdk_estimated_usd"] is not None for m in models):
            cost = sum(m["sdk_estimated_usd"] for m in models)
        # A crashed CLI can send a zeroed result after spending tokens. Keep the
        # observed input counts; never label an unknown crash cost as free.
        if message.subtype == "error_during_execution" and not total(tokens) and not cost:
            return self.partial(duration_ms, limit_usd)
        unknown_price = any(m["cost_basis"] == "unknown" for m in models)
        if unknown_price:
            cost = None
            for model in models:
                if model["cost_basis"] == "unknown":
                    model["sdk_estimated_usd"] = None
        return {"version": 2, "tokens": tokens, "total_tokens": total(tokens),
                "sdk_estimated_usd": cost, "models": models, "scope": scope,
                "coverage": "reported" if total(tokens) is not None else "partial", "note": NOTE,
                "turns": message.num_turns, "duration_ms": message.duration_ms,
                "wall_duration_ms": duration_ms, "limit_usd": limit_usd,
                "result_subtype": message.subtype, "unknown_price": unknown_price}


def job_usage(job):
    return normalize_usage(job.get("usage"))


def conversation_usage(jobs):
    rows = [job_usage(job) for job in jobs if job["status"] in TERMINAL]
    token_rows = [row for row in rows if row["total_tokens"] is not None]
    cost_rows = [row for row in rows if row["sdk_estimated_usd"] is not None]
    return {"tasks": len(rows), "token_tasks": len(token_rows), "cost_tasks": len(cost_rows),
            "total_tokens": sum(row["total_tokens"] for row in token_rows) if token_rows else None,
            "sdk_estimated_usd": sum(row["sdk_estimated_usd"] for row in cost_rows) if cost_rows else None,
            "incomplete_tasks": sum(row["coverage"] != "reported" for row in rows), "note": NOTE}


def csv_text(value):
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")) else text


def usage_csv(jobs):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Task ID", "Started UTC", "Task", "Status", "Usage coverage", "Token scope",
                     "Input tokens", "Output tokens", "Cache read tokens", "Cache write tokens", "Total tokens",
                     "SDK API estimate USD", "Blended estimate USD per 1000 tokens", "Wall seconds", "Waiting for user seconds", "Working seconds", "Model turns", "Models", "Task estimate limit USD", "Note"])
    for job in jobs:
        usage = job_usage(job)
        duration = usage["wall_duration_ms"] if usage["wall_duration_ms"] is not None else usage["duration_ms"]
        writer.writerow([csv_text(job["id"]), datetime.fromtimestamp(job["created"], timezone.utc).isoformat(),
                         csv_text(job["prompt"]), job["status"], usage["coverage"], usage["scope"],
                         *[usage["tokens"][key] for key in TOKEN_KEYS], usage["total_tokens"],
                         usage["sdk_estimated_usd"],
                         usage["sdk_estimated_usd"] * 1000 / usage["total_tokens"]
                         if usage["total_tokens"] and usage["sdk_estimated_usd"] is not None else None,
                         duration / 1000 if duration is not None else None,
                         usage['user_wait_ms'] / 1000 if usage.get('user_wait_ms') is not None else None,
                         usage['active_duration_ms'] / 1000 if usage.get('active_duration_ms') is not None else None,
                         usage["turns"], csv_text("; ".join(m["model"] for m in usage["models"])),
                         usage["limit_usd"], NOTE])
    return "\ufeff" + output.getvalue()
