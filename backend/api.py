"""FastAPI app factory for the AI Usage Dashboard."""
import os
import threading
import time
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse

from db import latest_usage, history, latest_quota, metrics
from db import connect as _db_connect, DB_PATH, init_schema
from util import parse_iso_seconds
from source_registry import get_all_names


def error_response(code: str, message: str, status: int = 400):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


def _agy_quota_to_api(raw: dict) -> dict:
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


_quota_cache: dict = {}
_QUOTA_TTL_SECONDS = 60

# Endpoints are sync `def` routes, so FastAPI runs each request in a
# threadpool worker -> concurrent requests are real concurrent threads, not
# coroutines on one loop, and a plain threading.Lock is the right primitive.
# One lock per source (not a single global lock) so refreshing 'codex' never
# blocks a concurrent request for 'claude'.
_quota_locks: dict = {}
_quota_locks_guard = threading.Lock()


def _lock_for(source: str) -> threading.Lock:
    with _quota_locks_guard:
        lock = _quota_locks.get(source)
        if lock is None:
            lock = _quota_locks[source] = threading.Lock()
        return lock


def _get_cached_quota(source: str, fetcher, force: bool = False):
    now = time.time()
    cached = _quota_cache.get(source)
    if not force and cached and (now - cached[0]) < _QUOTA_TTL_SECONDS:
        return cached[1]

    # Cache stampede guard: on expiry, every concurrent request for this
    # source would otherwise run the (slow: subprocess/network) fetcher and
    # block for tens of seconds. Only the first thread through the lock
    # fetches; the rest wait and then re-read the now-fresh cache.
    lock = _lock_for(source)
    with lock:
        cached = _quota_cache.get(source)
        if not force and cached and (time.time() - cached[0]) < _QUOTA_TTL_SECONDS:
            return cached[1]
        try:
            raw = fetcher()
        except Exception:
            raw = None
        if raw is None:
            raw = {'error': 'fetch failed'}
        _quota_cache[source] = (time.time(), raw)
        return raw


_VALID_SOURCES = set(get_all_names())


def create_app() -> FastAPI:
    app = FastAPI()

    # Schema creation belongs at startup, not per-request: init_schema runs
    # five CREATE TABLE IF NOT EXISTS, a PRAGMA introspection, a meta INSERT
    # OR IGNORE and a commit, which would otherwise turn every /ready and
    # /metrics hit into a writer contending with the poller's write lock.
    # main.py already does this before serving, but tests (and any other
    # embedder of create_app) construct the app directly, so do it once here
    # too rather than relying on the caller.
    conn = _db_connect(DB_PATH)
    try:
        init_schema(conn)
    finally:
        conn.close()

    @app.middleware("http")
    async def add_csp_header(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'"
        )
        return response

    @app.exception_handler(404)
    async def not_found(request, exc):
        return error_response("not_found", "The requested resource was not found", 404)

    @app.exception_handler(500)
    async def internal_error(request, exc):
        return error_response("internal", "An unexpected error occurred", 500)

    @app.get("/api/usage/latest")
    def api_latest(deltas: bool = Query(False)):
        conn = _db_connect(DB_PATH)
        try:
            return latest_usage(conn, include_model_deltas=deltas)
        finally:
            conn.close()

    @app.get("/api/usage/{source}/latest")
    def api_source_latest(source: str, deltas: bool = Query(False)):
        if source not in _VALID_SOURCES:
            return error_response("source_unknown", f"Unknown source: {source}", 404)
        conn = _db_connect(DB_PATH)
        try:
            data = latest_usage(conn, source=source, include_model_deltas=deltas)
            return data.get(source, {})
        finally:
            conn.close()

    @app.get("/api/usage/{source}/history")
    def api_source_history(source: str, range: str = Query('all'), with_models: bool = Query(None)):
        if source not in _VALID_SOURCES:
            return error_response("source_unknown", f"Unknown source: {source}", 404)
        
        start_ts = None
        if range != 'all':
            seconds_map = {
                '1h': 3600,
                '6h': 21600,
                '1d': 86400,
                '1w': 604800,
                '1m': 2592000,
                '3m': 7776000,
            }
            duration = seconds_map.get(range)
            if duration:
                conn = _db_connect(DB_PATH)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT MAX(cycle_ts) FROM usage_history WHERE source=?", (source,))
                    max_ts = cursor.fetchone()[0]
                    if max_ts:
                        start_ts = max_ts - duration
                finally:
                    conn.close()

        if with_models is None:
            with_models = (range != 'all')

        conn = _db_connect(DB_PATH)
        try:
            return history(conn, source=source, with_models=with_models, start_ts=start_ts)
        finally:
            conn.close()

    @app.get("/api/usage/history")
    def api_history(range: str = Query('all'), with_models: bool = Query(None)):
        start_ts = None
        if range != 'all':
            seconds_map = {
                '1h': 3600,
                '6h': 21600,
                '1d': 86400,
                '1w': 604800,
                '1m': 2592000,
                '3m': 7776000,
            }
            duration = seconds_map.get(range)
            if duration:
                conn = _db_connect(DB_PATH)
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT MAX(cycle_ts) FROM usage_history")
                    max_ts = cursor.fetchone()[0]
                    if max_ts:
                        start_ts = max_ts - duration
                finally:
                    conn.close()

        if with_models is None:
            with_models = (range != 'all')

        conn = _db_connect(DB_PATH)
        try:
            return history(conn, source=None, with_models=with_models, start_ts=start_ts)
        finally:
            conn.close()

    @app.get("/api/quota/latest")
    def api_quota_latest(force: bool = False):
        from quota_parser import fetch_agy_quota
        from codex_quota import fetch_codex_quota
        from opencode_quota import fetch_opencode_cost
        from claude_quota import fetch_claude_quota
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_agy = executor.submit(_get_cached_quota, 'agy', fetch_agy_quota, force)
            fut_opencode = executor.submit(_get_cached_quota, 'opencode', fetch_opencode_cost, force)
            fut_codex = executor.submit(_get_cached_quota, 'codex', fetch_codex_quota, force)
            fut_claude = executor.submit(_get_cached_quota, 'claude', fetch_claude_quota, force)

            raw_agy = fut_agy.result()
            opencode_live = fut_opencode.result()
            codex_live = fut_codex.result()
            claude_live = fut_claude.result()

        conn = _db_connect(DB_PATH)
        try:
            result = latest_quota(conn)
        finally:
            conn.close()

        if 'agy' not in result:
            result['agy'] = {}
        if raw_agy and 'error' not in raw_agy:
            result['agy'] = _agy_quota_to_api(raw_agy)
        elif raw_agy and 'plan' in raw_agy:
            result['agy']['_plan'] = raw_agy['plan']

        if 'opencode' not in result:
            result['opencode'] = {}
        if opencode_live and 'error' not in opencode_live:
            result['opencode']['_cost'] = opencode_live

        codex_live = _get_cached_quota('codex', fetch_codex_quota, force)
        if codex_live and 'error' not in codex_live:
            if 'codex' not in result:
                result['codex'] = {}
            plan = codex_live.get('plan_type') or codex_live.get('plan', 'free')
            result['codex']['_plan'] = plan
            if 'primary_used_pct' in codex_live:
                reset_at = codex_live.get('reset_at', 0)
                now = time.time()
                resets_in = max(0, int(reset_at - now)) if reset_at > now else 0
                result['codex']['openai'] = {
                    'rate_limit': {
                        'remaining_pct': 100.0 - codex_live['primary_used_pct'],
                        'used': codex_live['primary_used_pct'],
                        'total': 100.0,
                        'refreshes_in_seconds': resets_in,
                        'reset_at': reset_at,
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

        claude_live = _get_cached_quota('claude', fetch_claude_quota)
        if claude_live and 'error' not in claude_live:
            if 'claude' not in result:
                result['claude'] = {}
            plan_type = claude_live.get('subscription_type', 'pro')
            result['claude']['_plan'] = f"Claude {plan_type.title()}"
            if 'five_hour' in claude_live:
                fh = claude_live['five_hour']
                result['claude']['session'] = {
                    'five_hour': {
                        'used': fh.get('utilization', 0),
                        'total': 100.0,
                        'remaining_pct': 100.0 - fh.get('utilization', 0),
                        'refreshes_in_seconds': parse_iso_seconds(fh.get('resets_at', '')),
                    }
                }
            if 'seven_day' in claude_live:
                wd = claude_live['seven_day']
                result['claude']['weekly'] = {
                    'all_models': {
                        'used': wd.get('utilization', 0),
                        'total': 100.0,
                        'remaining_pct': 100.0 - wd.get('utilization', 0),
                        'refreshes_in_seconds': parse_iso_seconds(wd.get('resets_at', '')),
                    }
                }
            for lim in claude_live.get('limits', []):
                if lim.get('kind') == 'weekly_scoped':
                    scope_model = lim.get('scope', {}).get('model', {})
                    model_name = scope_model.get('display_name')
                    if model_name:
                        if 'weekly' not in result['claude']:
                            result['claude']['weekly'] = {}
                        result['claude']['weekly'][model_name] = {
                            'used': lim.get('percent', 0),
                            'total': 100.0,
                            'remaining_pct': 100.0 - lim.get('percent', 0),
                            'refreshes_in_seconds': parse_iso_seconds(lim.get('resets_at', '')),
                        }
        return result

    @app.get("/api/quota/{source}/latest")
    def api_quota_source_latest(source: str, force: bool = False):
        if source not in _VALID_SOURCES:
            return error_response("source_unknown", f"Unknown source: {source}", 404)

        from quota_parser import fetch_agy_quota
        from codex_quota import fetch_codex_quota
        from opencode_quota import fetch_opencode_cost
        from claude_quota import fetch_claude_quota

        conn = _db_connect(DB_PATH)
        try:
            db_result = latest_quota(conn, source=source)
        finally:
            conn.close()

        if source == 'agy':
            raw = _get_cached_quota('agy', fetch_agy_quota, force)
            if raw and 'error' not in raw:
                return {'agy': _agy_quota_to_api(raw)}
            if raw and 'plan' in raw:
                if db_result:
                    db_result['agy']['_plan'] = raw['plan']
                else:
                    db_result = {'agy': {'_plan': raw['plan']}}
            return db_result or {}

        elif source == 'opencode':
            result = db_result or {'opencode': {}}
            opencode_live = _get_cached_quota('opencode', fetch_opencode_cost, force)
            if opencode_live and 'error' not in opencode_live:
                result['opencode']['_cost'] = opencode_live
            return result

        elif source == 'codex':
            db_data = db_result or {}
            codex_live = _get_cached_quota('codex', fetch_codex_quota, force)
            if codex_live and 'error' not in codex_live:
                plan = codex_live.get('plan_type') or codex_live.get('plan', 'free')
                result = {'codex': {'_plan': plan, 'openai': {}}}
                if 'primary_used_pct' in codex_live:
                    reset_at = codex_live.get('reset_at', 0)
                    now = time.time()
                    resets_in = max(0, int(reset_at - now)) if reset_at > now else 0
                    result['codex']['openai']['rate_limit'] = {
                        'remaining_pct': 100.0 - codex_live['primary_used_pct'],
                        'used': codex_live['primary_used_pct'],
                        'total': 100.0,
                        'refreshes_in_seconds': resets_in,
                        'reset_at': reset_at,
                    }
                elif 'total_used_usd' in codex_live:
                    result['codex']['openai']['cost'] = {
                        'used': codex_live['total_used_usd'],
                        'total': codex_live.get('hard_limit_usd', 0),
                        'remaining': codex_live.get('remaining_usd', 0),
                    }
                return result
            return db_data or {}

        elif source == 'claude':
            db_data = db_result or {'claude': {}}
            claude_live = _get_cached_quota('claude', fetch_claude_quota)
            if claude_live and 'error' not in claude_live:
                plan_type = claude_live.get('subscription_type', 'pro')
                db_data['claude']['_plan'] = f"Claude {plan_type.title()}"
                if 'five_hour' in claude_live:
                    fh = claude_live['five_hour']
                    db_data['claude']['session'] = {
                        'five_hour': {
                            'used': fh.get('utilization', 0),
                            'total': 100.0,
                            'remaining_pct': 100.0 - fh.get('utilization', 0),
                            'refreshes_in_seconds': parse_iso_seconds(fh.get('resets_at', '')),
                        }
                    }
                if 'seven_day' in claude_live:
                    wd = claude_live['seven_day']
                    db_data['claude']['weekly'] = {
                        'all_models': {
                            'used': wd.get('utilization', 0),
                            'total': 100.0,
                            'remaining_pct': 100.0 - wd.get('utilization', 0),
                            'refreshes_in_seconds': parse_iso_seconds(wd.get('resets_at', '')),
                        }
                    }
                for lim in claude_live.get('limits', []):
                    if lim.get('kind') == 'weekly_scoped':
                        scope_model = lim.get('scope', {}).get('model', {})
                        model_name = scope_model.get('display_name')
                        if model_name:
                            if 'weekly' not in db_data['claude']:
                                db_data['claude']['weekly'] = {}
                            db_data['claude']['weekly'][model_name] = {
                                'used': lim.get('percent', 0),
                                'total': 100.0,
                                'remaining_pct': 100.0 - lim.get('percent', 0),
                                'refreshes_in_seconds': parse_iso_seconds(lim.get('resets_at', '')),
                            }
            return db_data

        return db_result or {}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        conn = _db_connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM collection_status WHERE ok=1")
        row = cursor.fetchone()
        conn.close()
        if row and row[0] > 0:
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/metrics")
    def get_metrics():
        from integrity import check_integrity
        from config import load_config
        conn = _db_connect(DB_PATH)
        result = metrics(conn)
        result['integrity'] = check_integrity(conn, load_config().poll_interval)
        conn.close()
        return result

    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def read_root():
        return RedirectResponse(url='/static/index.html')

    return app
