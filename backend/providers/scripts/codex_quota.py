def collect(**kwargs):
    from codex_quota import fetch_codex_quota
    codex_bin = kwargs.get('codex_bin', 'codex')
    timeout = kwargs.get('network_timeout', kwargs.get('timeout', 10))
    return fetch_codex_quota(codex_bin=codex_bin, timeout=timeout)


def normalize(raw):
    """Delegates to the canonical normalizer shared with source_registry."""
    from codex_quota import normalize_quota
    result = normalize_quota(raw)
    if result is None:
        return None
    # Legacy stored snapshots from the retired billing-API path.
    if 'openai' not in result and isinstance(raw, dict) and 'total_used_usd' in raw:
        result['openai'] = {
            'cost': {
                'used': raw['total_used_usd'],
                'total': raw.get('hard_limit_usd', 0),
                'remaining': raw.get('remaining_usd', 0),
            }
        }
    return result
