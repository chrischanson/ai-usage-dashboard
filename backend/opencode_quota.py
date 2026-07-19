import time
from parsers.opencode import OpenCodeParser

_CACHE = None  # (timestamp, dict)


def fetch_opencode_cost():
    global _CACHE
    now = time.time()
    if _CACHE and (now - _CACHE[0]) < 60:
        return _CACHE[1]

    try:
        result = OpenCodeParser(timeout=2.5).parse()
        cost_by_model = {m.model_name: m.cost for m in result.models if m.cost}
        data = {
            'total_cost': sum(cost_by_model.values()),
            'cost_by_model': cost_by_model,
        }
        _CACHE = (now, data)
        return data
    except Exception as e:
        if _CACHE:
            return _CACHE[1]
        return {'error': str(e)}
