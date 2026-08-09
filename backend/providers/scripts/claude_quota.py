def collect(**kwargs):
    from claude_quota import fetch_claude_quota
    return fetch_claude_quota()

def normalize(raw):
    if not raw or 'error' in raw:
        return None
    from util import parse_iso_seconds
    result = {}
    plan = raw.get('subscription_type', 'pro')
    result['_plan'] = f"Claude {plan.title()}"
    if 'five_hour' in raw:
        fh = raw['five_hour']
        result['session'] = {
            'five_hour': {
                'used': fh.get('utilization', 0.0),
                'total': 100.0,
                'remaining_pct': 100.0 - fh.get('utilization', 0.0),
                'refreshes_in_seconds': parse_iso_seconds(fh.get('resets_at', '')),
            }
        }
    if 'seven_day' in raw:
        wd = raw['seven_day']
        result['weekly'] = {
            'all_models': {
                'used': wd.get('utilization', 0.0),
                'total': 100.0,
                'remaining_pct': 100.0 - wd.get('utilization', 0.0),
                'refreshes_in_seconds': parse_iso_seconds(wd.get('resets_at', '')),
            }
        }
    for lim in raw.get('limits', []):
        if lim.get('kind') == 'weekly_scoped':
            scope_model = lim.get('scope', {}).get('model', {})
            model_name = scope_model.get('display_name')
            if model_name:
                if 'weekly' not in result:
                    result['weekly'] = {}
                result['weekly'][model_name] = {
                    'used': lim.get('percent', 0.0),
                    'total': 100.0,
                    'remaining_pct': 100.0 - lim.get('percent', 0.0),
                    'refreshes_in_seconds': parse_iso_seconds(lim.get('resets_at', '')),
                }
    return result
