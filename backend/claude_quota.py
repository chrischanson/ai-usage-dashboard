"""
Parser for Claude (Claude Code) quota data.
Reads OAuth credentials from ~/.claude/.credentials.json and queries
the Anthropic usage API for 5-hour session and weekly limits.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

CREDENTIALS_PATH = os.path.expanduser('~/.claude/.credentials.json')
USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'
_NETWORK_TIMEOUT = 10


def fetch_claude_quota():
    """
    Fetch Claude usage quota from the Anthropic API.

    Returns dict with:
      - five_hour: {utilization, resets_at}
      - seven_day: {utilization, resets_at}
      - limits: [...] per-model weekly limits
      - subscription_type: 'pro' / 'max' / etc.
    Or {'error': ...} on failure.
    """
    if os.environ.get('USAGE_MOCK_CLAUDE') == '1':
        return {
            'subscription_type': 'pro',
            'five_hour': {
                'utilization': 35.0,
                'resets_at': '2026-07-03T18:00:00Z',
            },
            'seven_day': {
                'utilization': 45.0,
                'resets_at': '2026-07-05T00:00:00Z',
            },
            'limits': [
                {
                    'kind': 'weekly_scoped',
                    'scope': {
                        'model': {
                            'display_name': 'Claude 3.5 Sonnet'
                        }
                    },
                    'percent': 55.0,
                    'resets_at': '2026-07-05T00:00:00Z',
                },
                {
                    'kind': 'weekly_scoped',
                    'scope': {
                        'model': {
                            'display_name': 'Claude 3 Opus'
                        }
                    },
                    'percent': 15.0,
                    'resets_at': '2026-07-05T00:00:00Z',
                }
            ]
        }

    if not os.path.exists(CREDENTIALS_PATH):
        return {'error': 'Claude credentials file not found'}

    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {'error': f'Failed to read credentials: {e}'}

    access_token = creds.get('claudeAiOauth', {}).get('accessToken')
    subscription_type = creds.get('claudeAiOauth', {}).get('subscriptionType', 'pro')
    expires_at = creds.get('claudeAiOauth', {}).get('expiresAt', 0)

    if not access_token:
        return {'error': 'No access token in credentials'}

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if expires_at and expires_at <= now_ms:
        return {'error': 'Token expired', 'subscription_type': subscription_type}

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            'Authorization': f'Bearer {access_token}',
            'anthropic-beta': 'oauth-2025-04-20',
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=_NETWORK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return {
            'error': f'HTTP {e.code}: {e.reason}',
            'subscription_type': subscription_type,
        }
    except Exception as e:
        return {
            'error': str(e),
            'subscription_type': subscription_type,
        }

    result = {
        'subscription_type': subscription_type,
    }

    if 'five_hour' in data:
        result['five_hour'] = {
            'utilization': data['five_hour'].get('utilization', 0),
            'resets_at': data['five_hour'].get('resets_at', ''),
        }

    if 'seven_day' in data:
        result['seven_day'] = {
            'utilization': data['seven_day'].get('utilization', 0),
            'resets_at': data['seven_day'].get('resets_at', ''),
        }

    if 'limits' in data:
        result['limits'] = data['limits']

    return result
