import os
import sys

# Ensure backend package can be imported if run directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db import init_db, insert_usage, insert_quota
from backend.parser import fetch_and_parse
from backend.agy_parser import fetch_agy_usage
from backend.codex_parser import fetch_codex_usage
from backend.quota_parser import fetch_agy_quota


def run_poll():
    init_db()
    
    # --- OpenCode usage ---
    try:
        overview, cost_tokens, models = fetch_and_parse()
        if overview or cost_tokens:
            insert_usage(overview, cost_tokens, models, source='opencode')
            print("[poll] Successfully saved OpenCode usage snapshot.")
    except Exception as e:
        print(f"[poll] OpenCode error: {e}", file=sys.stderr)

    # --- Antigravity usage ---
    try:
        overview, cost_tokens, models = fetch_agy_usage()
        if overview or cost_tokens:
            insert_usage(overview, cost_tokens, models, source='agy')
            print("[poll] Successfully saved Antigravity usage snapshot.")
    except Exception as e:
        print(f"[poll] Antigravity error: {e}", file=sys.stderr)

    # --- Codex usage ---
    try:
        overview, cost_tokens, models = fetch_codex_usage()
        if overview or cost_tokens:
            insert_usage(overview, cost_tokens, models, source='codex')
            print("[poll] Successfully saved Codex usage snapshot.")
    except Exception as e:
        print(f"[poll] Codex error: {e}", file=sys.stderr)

    # --- AGY quota (limits) ---
    try:
        quota = fetch_agy_quota()
        if quota and 'error' not in quota:
            insert_quota(quota)
            print("[poll] Successfully saved AGY quota snapshot.")
        elif quota:
            print(f"[poll] AGY quota fetch returned: {quota.get('error')}")
    except Exception as e:
        print(f"[poll] AGY quota error: {e}", file=sys.stderr)


if __name__ == '__main__':
    run_poll()
