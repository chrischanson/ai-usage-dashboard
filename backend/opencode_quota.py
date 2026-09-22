import time
from parsers.opencode import OpenCodeParser, get_cached_parse

_CACHE = None  # (timestamp, dict)

# Freshness window for reusing the usage parser's result instead of
# spawning `opencode stats` a second time in the same poll cycle. Matches
# the default poll interval plus headroom; the poller runs usage then quota
# back-to-back, so a hit avoids the duplicate subprocess on every cycle.
_REUSE_WINDOW_SECONDS = 660


def _cost_from_result(result):
    cost_by_model = {m.model_name: m.cost for m in result.models if m.cost}
    return {
        'total_cost': sum(cost_by_model.values()),
        'cost_by_model': cost_by_model,
    }


def fetch_opencode_cost():
    global _CACHE
    now = time.time()
    # Fast path: the usage parser already ran `opencode stats --models`
    # seconds ago in this same poll cycle — reuse its per-model costs.
    cached_parse = get_cached_parse(max_age_seconds=_REUSE_WINDOW_SECONDS)
    if cached_parse is not None:
        data = _cost_from_result(cached_parse)
        _CACHE = (now, data)
        return data
    if _CACHE and (now - _CACHE[0]) < _REUSE_WINDOW_SECONDS:
        return _CACHE[1]

    try:
        from config import load_config
        cfg = load_config()
        result = OpenCodeParser(timeout=cfg.subprocess_timeout,
                                opencode_bin=cfg.opencode_bin).parse()
        data = _cost_from_result(result)
        _CACHE = (now, data)
        return data
    except Exception as e:
        if _CACHE:
            return _CACHE[1]
        return {'error': str(e)}
