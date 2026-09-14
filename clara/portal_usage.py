"""Map a single local attempt's measured usage without pricing the Max plan."""
import math
import json

from .usage import normalize_usage, number


def _tokens(value):
    return value if type(value) is int and 0 <= value <= 9007199254740991 else None


def portal_usage(raw, *, wall_seconds, waiting_seconds):
    if (number(wall_seconds) is None or number(waiting_seconds) is None
            or waiting_seconds > wall_seconds or wall_seconds > 9007199254740991):
        raise ValueError('Provide measured elapsed and waiting time for this attempt.')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    raw = raw if isinstance(raw, dict) else {}
    usage = normalize_usage(raw)
    # The legacy normalizer defaults absent cache categories to zero. For the
    # portal report those categories remain unknown unless actually recorded.
    tokens = raw.get('tokens') if isinstance(raw.get('tokens'), dict) else {}
    input_count = _tokens(tokens.get('input_tokens'))
    output_count = _tokens(tokens.get('output_tokens'))
    reads = _tokens(tokens.get('cache_read_input_tokens'))
    writes = _tokens(tokens.get('cache_creation_input_tokens'))
    cached = _tokens(reads + writes) if reads is not None and writes is not None else None
    cost = number(usage.get('sdk_estimated_usd'))
    if usage.get('unknown_price'):
        cost = None
    known = [input_count, output_count, cached, cost]
    coverage = ('complete' if usage.get('coverage') == 'reported' and all(v is not None for v in known)
                else 'partial' if any(v is not None for v in known) else 'unknown')
    elapsed = math.ceil(wall_seconds)
    waiting = min(elapsed, math.ceil(waiting_seconds))
    return {'active_seconds': elapsed - waiting, 'waiting_seconds': waiting,
            'input_tokens': input_count, 'output_tokens': output_count,
            'cache_tokens': cached, 'estimated_cost_usd': cost, 'usage_coverage': coverage}
