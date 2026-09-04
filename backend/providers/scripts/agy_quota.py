def collect(**kwargs):
    from quota_parser import fetch_agy_quota
    # provider_loader passes configuration through; fall back to loading it
    # here for any caller that invokes collect() directly.
    timeout = kwargs.get('network_timeout')
    if timeout is None:
        from config import load_config
        timeout = load_config().network_timeout
    return fetch_agy_quota(network_timeout=timeout)

def normalize(raw):
    if not raw or 'error' in raw:
        return None
    result = {}
    plan = raw.get('plan', 'Gemini Code Assist')
    result['_plan'] = plan
    for group_key, limits in raw.items():
        if group_key == 'plan' or not isinstance(limits, dict):
            continue
        result[group_key] = {}
        for limit_key, info in limits.items():
            if not isinstance(info, dict):
                continue
            result[group_key][limit_key] = {
                'used': info.get('used', 0.0),
                'total': info.get('total', 100.0),
                'remaining_pct': info.get('remaining_pct', 0.0),
                'refreshes_in_seconds': info.get('refreshes_in', info.get('refreshes_in_seconds', 0)),
            }
    return result
