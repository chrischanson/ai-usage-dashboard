import base64
import json
import os
import re
import sqlite3
from datetime import date, timedelta
import urllib.request

OPENAI_BILLING_URL = 'https://api.openai.com/v1/dashboard/billing'
AUTH_PATH = os.path.expanduser('~/.codex/auth.json')
CODEX_DB = os.path.expanduser('~/.codex/state_5.sqlite')
CODEX_LOGS = os.path.expanduser('~/.codex/logs_2.sqlite')


def _get_plan_from_jwt():
    """Extract plan type and account info from the JWT token in auth.json."""
    if not os.path.exists(AUTH_PATH):
        return None
    try:
        with open(AUTH_PATH) as f:
            auth = json.load(f)
        tokens = auth.get('tokens', {})
        for token_key in ('access_token', 'id_token'):
            token = tokens.get(token_key, '')
            if not token:
                continue
            parts = token.split('.')
            if len(parts) != 3:
                continue
            padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
            try:
                payload = json.loads(base64.urlsafe_b64decode(padded))
            except Exception:
                continue
            auth_data = payload.get('https://api.openai.com/auth', {})
            if auth_data.get('chatgpt_plan_type'):
                return {
                    'plan_type': auth_data['chatgpt_plan_type'],
                    'account_id': auth_data.get('chatgpt_account_id', ''),
                    'org_id': (auth_data.get('organizations') or [{}])[0].get('id', ''),
                }
        return {'plan_type': 'unknown'}
    except Exception:
        return {'plan_type': 'unknown'}


def _parse_logs_for_limits():
    if not os.path.exists(CODEX_LOGS):
        return None
    try:
        conn = sqlite3.connect(CODEX_LOGS)
        cursor = conn.execute(
            "SELECT feedback_log_body FROM logs WHERE feedback_log_body LIKE '%codex.rate_limits%' ORDER BY id DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        body = row[0]
        idx = body.find('"type":"codex.rate_limits"')
        if idx < 0:
            conn.close()
            return None
        # Find the opening { before type, then use json.JSONDecoder to find the matching }
        start = body.rfind('{', 0, idx)
        if start < 0:
            conn.close()
            return None
        try:
            data, _ = json.JSONDecoder().raw_decode(body, start)
        except json.JSONDecodeError:
            conn.close()
            return None
        limits = data.get('rate_limits', {})
        primary = limits.get('primary', {})
        return {
            'plan_type': data.get('plan_type', 'unknown'),
            'primary_used_pct': float(primary.get('used_percent', 0)),
            'window_minutes': int(primary.get('window_minutes', 0)),
            'resets_in_seconds': int(primary.get('reset_after_seconds', 0)),
            'reset_at': int(primary.get('reset_at', 0)),
            'limit_reached': limits.get('limit_reached', False),
            'allowed': limits.get('allowed', True),
        }
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _get_token_stats():
    if not os.path.exists(CODEX_DB):
        return None
    try:
        conn = sqlite3.connect(CODEX_DB)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT model, tokens_used FROM threads")
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()
    except Exception:
        return None
    if not rows:
        return None
    model_sessions = {}
    total_tokens = 0
    for model, tokens in rows:
        tokens = tokens or 0
        model_sessions[model] = model_sessions.get(model, 0) + 1
        total_tokens += tokens
    return {
        'total_sessions': len(rows),
        'total_tokens': total_tokens,
        'model_sessions': model_sessions,
    }


def fetch_codex_quota():
    # Get plan from JWT (always available)
    plan_info = _get_plan_from_jwt()

    # Try real OpenAI billing API first (requires API key)
    if os.path.exists(AUTH_PATH):
        with open(AUTH_PATH) as f:
            auth = json.load(f)
        api_key = auth.get('OPENAI_API_KEY')
        if api_key:
            try:
                req = urllib.request.Request(
                    f'{OPENAI_BILLING_URL}/subscription',
                    headers={'Authorization': f'Bearer {api_key}'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    sub = json.loads(resp.read())
                today = date.today()
                start = today.replace(day=1)
                req2 = urllib.request.Request(
                    f'{OPENAI_BILLING_URL}/usage?start_date={start}&end_date={today}',
                    headers={'Authorization': f'Bearer {api_key}'}
                )
                with urllib.request.urlopen(req2, timeout=10) as resp:
                    usage = json.loads(resp.read())
                total_used = usage.get('total_usage', 0) / 100.0
                hard_limit = sub.get('hard_limit_usd', 0)
                soft_limit = sub.get('soft_limit_usd', 0)
                plan = sub.get('plan', {}).get('title', 'Unknown')
                remaining = max(0, hard_limit - total_used) if hard_limit else None
                return {
                    'plan': plan,
                    'total_used_usd': total_used,
                    'hard_limit_usd': hard_limit,
                    'remaining_usd': remaining,
                }
            except urllib.error.HTTPError as e:
                return {'error': f'OpenAI API error: {e.code} {e.reason}'}
            except Exception as e:
                return {'error': str(e)}

    limits = _parse_logs_for_limits()
    tokens = _get_token_stats()

    result = {}

    if plan_info:
        plan_label = plan_info.get('plan_type', 'free').capitalize()
        if plan_label == 'Free':
            result['plan'] = 'Codex (Free)'
        else:
            result['plan'] = f'Codex ({plan_label})'
        result['plan_type'] = plan_info['plan_type']

    if limits:
        result.update({
            'primary_used_pct': limits['primary_used_pct'],
            'window_minutes': limits['window_minutes'],
            'resets_in_seconds': limits['resets_in_seconds'],
        })

    if tokens:
        result['tokens'] = tokens

    if not limits and not tokens:
        return {'error': 'No Codex data found.'}

    return result
