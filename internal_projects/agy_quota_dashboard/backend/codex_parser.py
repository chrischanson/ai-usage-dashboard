"""
Parser for OpenAI Codex CLI usage data.
Reads token usage from Codex's SQLite databases.
"""
import sqlite3
import os
import glob

CODEX_STATE_DB = os.path.expanduser('~/.codex/state_5.sqlite')
CODEX_LOGS_DB = os.path.expanduser('~/.codex/logs_2.sqlite')


def fetch_codex_usage():
    """
    Read Codex usage from local SQLite databases.

    Returns: (overview, cost_tokens, models) matching the same format as
    parse_report_content() in parser.py and fetch_agy_usage() in agy_parser.py.
    """
    if not os.path.isfile(CODEX_STATE_DB):
        return {}, {}, []

    try:
        conn = sqlite3.connect(f'file:{CODEX_STATE_DB}?mode=ro', uri=True)

        rows = conn.execute('''
            SELECT model, COUNT(*) as sessions,
                   COALESCE(SUM(tokens_used), 0) as total_tokens
            FROM threads
            WHERE tokens_used > 0
            GROUP BY model
            ORDER BY total_tokens DESC
        ''').fetchall()

        total_sessions = conn.execute(
            'SELECT COUNT(*) FROM threads WHERE tokens_used > 0'
        ).fetchone()[0]

        total_tokens = conn.execute(
            'SELECT COALESCE(SUM(tokens_used), 0) FROM threads WHERE tokens_used > 0'
        ).fetchone()[0]

        conn.close()
    except Exception:
        return {}, {}, []

    if not rows:
        return {}, {}, []

    overview = {
        'Sessions': total_sessions,
        'Messages': total_sessions,
    }

    models = []
    for model, sessions, tokens in rows:
        models.append({
            'name': model,
            'Messages': sessions,
            'Input Tokens': tokens,
            'Output Tokens': 0,
            'Cache Read': 0,
            'Cache Write': 0,
            'Cost': 0.0,
        })

    cost_tokens = {
        'Total Cost': 0.0,
        'Avg Cost/Day': 0.0,
        'Input': total_tokens,
        'Output': 0,
        'Cache Read': 0,
        'Cache Write': 0,
    }

    return overview, cost_tokens, models
