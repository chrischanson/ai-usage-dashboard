"""Source registry — single source of truth for all data sources.

Each source defines:
  - name: canonical source key (e.g. 'opencode')
  - parser: callable returning ParserResult (raises SourceUnavailable on failure)
  - quota_collector: callable returning dict with quota data (or None/error)
  - quota_normalizer: callable that converts raw quota dict into the nested
    group→limit dict the DB/frontend expects; None means no normalization
  - display_name: human-readable label for the frontend

Adding a new source is a one-line change here plus the quota normalizer.
"""

from parsers.base import ParserResult


class _SourceEntry:
    __slots__ = ('name', 'parser', 'quota_collector', 'quota_normalizer', 'display_name', 'color', 'has_quota')

    def __init__(self, name, parser=None, quota_collector=None,
                 quota_normalizer=None, display_name=None, color=None, has_quota=False):
        self.name = name
        self.parser = parser
        self.quota_collector = quota_collector
        self.quota_normalizer = quota_normalizer
        self.display_name = display_name or name.title()
        self.color = color
        self.has_quota = has_quota


def _make_opencode_parser():
    from parsers.opencode import OpenCodeParser
    from config import load_config
    # Route the process-wide subprocess_timeout config through instead of
    # relying on OpenCodeParser's own hardcoded default.
    return OpenCodeParser(timeout=load_config().subprocess_timeout)


def _make_agy_parser():
    from parsers.agy import AgyParser
    return AgyParser()


def _make_codex_parser():
    from parsers.codex import CodexParser
    return CodexParser()


def _make_claude_parser():
    from parsers.claude import ClaudeParser
    return ClaudeParser()


def _opencode_quota():
    from opencode_quota import fetch_opencode_cost
    return fetch_opencode_cost()


def _agy_quota():
    from quota_parser import fetch_agy_quota
    from config import load_config
    return fetch_agy_quota(network_timeout=load_config().network_timeout)


def _codex_quota():
    from codex_quota import fetch_codex_quota
    return fetch_codex_quota()


def _claude_quota():
    from claude_quota import fetch_claude_quota
    return fetch_claude_quota()


def _normalize_opencode(raw):
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


def _normalize_agy(raw):
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


def _normalize_codex(raw):
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


def _normalize_claude(raw):
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


# --- The registry ---

_SOURCES: dict[str, _SourceEntry] = {}


def _register(entry: _SourceEntry):
    _SOURCES[entry.name] = entry


_register(_SourceEntry(
    name='opencode',
    parser=_make_opencode_parser,
    quota_collector=_opencode_quota,
    quota_normalizer=_normalize_opencode,
    display_name='OpenCode',
))

_register(_SourceEntry(
    name='agy',
    parser=_make_agy_parser,
    quota_collector=_agy_quota,
    quota_normalizer=_normalize_agy,
    display_name='Antigravity',
))

_register(_SourceEntry(
    name='codex',
    parser=_make_codex_parser,
    quota_collector=_codex_quota,
    quota_normalizer=_normalize_codex,
    display_name='Codex',
))

_register(_SourceEntry(
    name='claude',
    parser=_make_claude_parser,
    quota_collector=_claude_quota,
    quota_normalizer=_normalize_claude,
    display_name='Claude',
))


def get_source(name: str) -> _SourceEntry | None:
    return _SOURCES.get(name)


def get_all_sources() -> dict[str, _SourceEntry]:
    return dict(_SOURCES)


def get_all_names() -> list[str]:
    return list(_SOURCES.keys())


def get_all_display_names() -> dict[str, str]:
    return {name: entry.display_name for name, entry in _SOURCES.items()}


def is_valid_source(name: str) -> bool:
    return name in _SOURCES


def load_from_providers(providers_dir: str, cfg) -> None:
    """Replace the hardcoded registry with providers loaded from YAML files.

    If the *providers_dir* exists and contains at least one valid provider,
    the current registry is cleared and repopulated from YAML. Otherwise
    the hardcoded fallback entries (above) remain active.
    """
    import os
    from provider_loader import load_providers

    if os.path.isdir(providers_dir):
        new_sources = load_providers(providers_dir, cfg)
        if new_sources:
            _SOURCES.clear()
            for name, entry in new_sources.items():
                _register(entry)

