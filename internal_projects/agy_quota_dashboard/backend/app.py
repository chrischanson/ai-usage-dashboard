import threading
import time
import os
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from .db import (
    init_db, insert_usage, get_latest_usage, get_history_series,
    insert_quota, get_latest_quota,
)
from .parser import fetch_and_parse
from .agy_parser import fetch_agy_usage
from .codex_parser import fetch_codex_usage
from .quota_parser import fetch_agy_quota
from .opencode_quota import fetch_opencode_cost
from .codex_quota import fetch_codex_quota

app = FastAPI()

POLL_INTERVAL_SECONDS = 600  # 10 minutes


def _poll_loop():
    while True:
        # --- OpenCode usage (via opencode stats --models) ---
        try:
            overview, cost_tokens, models = fetch_and_parse()
            if overview or cost_tokens:
                insert_usage(overview, cost_tokens, models, source='opencode')
        except Exception as e:
            print(f"[poll] opencode error: {e}")

        # --- Antigravity usage (via local conversation DBs) ---
        try:
            overview, cost_tokens, models = fetch_agy_usage()
            if overview or cost_tokens:
                insert_usage(overview, cost_tokens, models, source='agy')
        except Exception as e:
            print(f"[poll] agy error: {e}")

        # --- Codex usage (via local SQLite DBs) ---
        try:
            overview, cost_tokens, models = fetch_codex_usage()
            if overview or cost_tokens:
                insert_usage(overview, cost_tokens, models, source='codex')
        except Exception as e:
            print(f"[poll] codex error: {e}")

        # --- AGY quota (limits from /usage) ---
        try:
            quota = fetch_agy_quota()
            if quota and 'error' not in quota:
                insert_quota(quota, source='agy')
        except Exception as e:
            print(f"[poll] agy quota error: {e}")

        # --- OpenCode cost (parsed from stats) ---
        try:
            cost = fetch_opencode_cost()
            if cost and 'error' not in cost:
                insert_quota({
                    'opencode': {
                        'total_cost': {
                            'used': cost['total_cost'],
                            'total': 0,
                            'remaining_pct': 100.0,
                            'refreshes_in': 0,
                        }
                    }
                }, source='opencode')
        except Exception as e:
            print(f"[poll] opencode cost error: {e}")

        # --- Codex quota (rate limits from logs OR billing API) ---
        try:
            codex_q = fetch_codex_quota()
            if codex_q and 'error' not in codex_q:
                if 'primary_used_pct' in codex_q:
                    insert_quota({
                        'openai': {
                            'rate_limit': {
                                'remaining_pct': 100.0 - codex_q['primary_used_pct'],
                                'used': codex_q['primary_used_pct'],
                                'total': 100.0,
                                'refreshes_in_seconds': codex_q.get('resets_in_seconds', 0),
                            }
                        }
                    }, source='codex')
                elif 'total_used_usd' in codex_q:
                    insert_quota({
                        'openai': {
                            'cost': {
                                'used': codex_q['total_used_usd'],
                                'total': codex_q.get('hard_limit_usd', 0),
                                'remaining': codex_q.get('remaining_usd', 0),
                            }
                        }
                    }, source='codex')
        except Exception as e:
            print(f"[poll] codex quota error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def startup_event():
    init_db()
    t = threading.Thread(target=_poll_loop, daemon=True)
    t.start()


# --- API routes ---

@app.get("/api/usage/latest")
def api_latest(deltas: bool = Query(False)):
    """Returns latest snapshot for both sources."""
    return get_latest_usage(include_model_deltas=deltas)


@app.get("/api/usage/opencode/latest")
def api_opencode_latest(deltas: bool = Query(False)):
    data = get_latest_usage(source='opencode', include_model_deltas=deltas)
    return data.get('opencode', {})


@app.get("/api/usage/agy/latest")
def api_agy_latest(deltas: bool = Query(False)):
    data = get_latest_usage(source='agy', include_model_deltas=deltas)
    return data.get('agy', {})


@app.get("/api/usage/opencode/history")
def api_opencode_history():
    return get_history_series(source='opencode')


@app.get("/api/usage/agy/history")
def api_agy_history():
    return get_history_series(source='agy')


@app.get("/api/usage/codex/latest")
def api_codex_latest(deltas: bool = Query(False)):
    data = get_latest_usage(source='codex', include_model_deltas=deltas)
    return data.get('codex', {})


@app.get("/api/usage/codex/history")
def api_codex_history():
    return get_history_series(source='codex')


@app.get("/api/usage/history")
def api_history():
    return get_history_series(source='opencode')


# --- Quota API ---

@app.get("/api/quota/latest")
def api_quota_latest():
    """Returns latest quota limits for all sources."""
    result = get_latest_quota()
    # Include AGY plan
    if 'agy' in result:
        raw = fetch_agy_quota()
        if raw and 'plan' in raw:
            result['agy']['_plan'] = raw['plan']
    # Include codex plan and ensure live data
    codex_live = fetch_codex_quota()
    if codex_live and 'error' not in codex_live:
        if 'codex' not in result:
            result['codex'] = {}
        # plan_type from logs, plan from billing API
        plan = codex_live.get('plan_type') or codex_live.get('plan', 'free')
        result['codex']['_plan'] = plan
        if 'primary_used_pct' in codex_live:
            result['codex']['openai'] = {
                'rate_limit': {
                    'remaining_pct': 100.0 - codex_live['primary_used_pct'],
                    'used': codex_live['primary_used_pct'],
                    'total': 100.0,
                    'refreshes_in_seconds': codex_live.get('resets_in_seconds', 0),
                }
            }
        elif 'total_used_usd' in codex_live:
            result['codex']['openai'] = {
                'cost': {
                    'used': codex_live['total_used_usd'],
                    'total': codex_live.get('hard_limit_usd', 0),
                    'remaining': codex_live.get('remaining_usd', 0),
                }
            }
    return result


@app.get("/api/quota/agy/latest")
def api_quota_agy_latest():
    result = get_latest_quota(source='agy')
    raw = fetch_agy_quota()
    if raw and 'plan' in raw:
        if result:
            result['agy']['_plan'] = raw['plan']
        else:
            result = {'agy': {'_plan': raw['plan']}}
    return result or {}


@app.get("/api/quota/opencode/latest")
def api_quota_opencode_latest():
    return get_latest_quota(source='opencode')


@app.get("/api/quota/codex/latest")
def api_quota_codex_latest():
    db_data = get_latest_quota(source='codex')
    codex_live = fetch_codex_quota()
    if codex_live and 'error' not in codex_live:
        plan = codex_live.get('plan_type') or codex_live.get('plan', 'free')
        if db_data:
            db_data['codex']['_plan'] = plan
            return db_data
        result = {'codex': {'_plan': plan, 'openai': {}}}
        if 'primary_used_pct' in codex_live:
            result['codex']['openai']['rate_limit'] = {
                'remaining_pct': 100.0 - codex_live['primary_used_pct'],
                'used': codex_live['primary_used_pct'],
                'total': 100.0,
                'refreshes_in_seconds': codex_live.get('resets_in_seconds', 0),
            }
        elif 'total_used_usd' in codex_live:
            result['codex']['openai']['cost'] = {
                'used': codex_live['total_used_usd'],
                'total': codex_live.get('hard_limit_usd', 0),
                'remaining': codex_live.get('remaining_usd', 0),
            }
        return result
    return db_data or {}


# --- Static frontend ---
frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def read_root():
    return RedirectResponse(url='/static/index.html')
