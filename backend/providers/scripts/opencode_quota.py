def collect(**kwargs):
    from opencode_quota import fetch_opencode_cost
    return fetch_opencode_cost()

def normalize(raw):
    if not raw or 'error' in raw:
        return None
    return {
        'opencode': {
            'total_cost': {
                'used': raw.get('total_cost', 0),
                'total': 0,
                'remaining_pct': 100.0,
                'refreshes_in_seconds': 0,
            }
        }
    }
