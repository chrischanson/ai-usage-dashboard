def collect(**kwargs):
    from codex_quota import fetch_codex_quota
    return fetch_codex_quota()

def normalize(raw):
    if not raw or 'error' in raw:
        return None
    import time
    result = {}
    plan = raw.get('plan_type') or raw.get('plan', 'free')
    result['_plan'] = plan
    if 'primary_used_pct' in raw:
        reset_at = raw.get('reset_at', 0)
        now = time.time()
        resets_in = max(0, int(reset_at - now)) if reset_at > now else raw.get('resets_in_seconds', 0)
        result['openai'] = {
            'rate_limit': {
                'remaining_pct': 100.0 - raw['primary_used_pct'],
                'used': raw['primary_used_pct'],
                'total': 100.0,
                'refreshes_in_seconds': resets_in,
                'reset_at': reset_at,
                'window_minutes': raw.get('window_minutes', 0),
            }
        }
    elif 'total_used_usd' in raw:
        result['openai'] = {
            'cost': {
                'used': raw['total_used_usd'],
                'total': raw.get('hard_limit_usd', 0),
                'remaining': raw.get('remaining_usd', 0),
            }
        }
    return result
