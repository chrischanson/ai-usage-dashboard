"""FastAPI app factory for the AI Usage Dashboard."""
import os
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from db import get_latest_usage, get_history_series, get_latest_quota, metrics
from db import connect as _db_connect, DB_PATH, init_schema
from quota_parser import fetch_agy_quota
from codex_quota import fetch_codex_quota
from opencode_quota import fetch_opencode_cost


def error_response(code: str, message: str, status: int = 400):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


def create_app() -> FastAPI:
    app = FastAPI()

    # --- CSP Middleware ---
    @app.middleware("http")
    async def add_csp_header(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'"
        )
        return response

    # --- Error handlers ---
    @app.exception_handler(404)
    async def not_found(request, exc):
        return error_response("not_found", "The requested resource was not found", 404)

    @app.exception_handler(500)
    async def internal_error(request, exc):
        return error_response("internal", "An unexpected error occurred", 500)

    # --- Usage routes ---
    @app.get("/api/usage/latest")
    def api_latest(deltas: bool = Query(False)):
        return get_latest_usage(include_model_deltas=deltas)

    @app.get("/api/usage/opencode/latest")
    def api_opencode_latest(deltas: bool = Query(False)):
        data = get_latest_usage(source='opencode', include_model_deltas=deltas)
        return data.get('opencode', {})

    @app.get("/api/usage/agy/latest")
    def api_agy_latest(deltas: bool = Query(False)):
        data = get_latest_usage(source='agy', include_model_deltas=deltas)
        return data.get('agy', {})

    @app.get("/api/usage/codex/latest")
    def api_codex_latest(deltas: bool = Query(False)):
        data = get_latest_usage(source='codex', include_model_deltas=deltas)
        return data.get('codex', {})

    @app.get("/api/usage/opencode/history")
    def api_opencode_history():
        return get_history_series(source='opencode')

    @app.get("/api/usage/agy/history")
    def api_agy_history():
        return get_history_series(source='agy')

    @app.get("/api/usage/codex/history")
    def api_codex_history():
        return get_history_series(source='codex')

    @app.get("/api/usage/history")
    def api_history():
        return get_history_series(source='opencode')

    # --- Quota routes ---
    @app.get("/api/quota/latest")
    def api_quota_latest():
        result = get_latest_quota()

        if 'agy' not in result:
            result['agy'] = {}
        raw = fetch_agy_quota()
        if raw and 'plan' in raw:
            result['agy']['_plan'] = raw['plan']

        if 'opencode' not in result:
            result['opencode'] = {}
        opencode_live = fetch_opencode_cost()
        if opencode_live and 'error' not in opencode_live:
            result['opencode']['_cost'] = opencode_live

        codex_live = fetch_codex_quota()
        if codex_live and 'error' not in codex_live:
            if 'codex' not in result:
                result['codex'] = {}
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
        result = get_latest_quota(source='opencode')
        if not result:
            result = {'opencode': {}}
        opencode_live = fetch_opencode_cost()
        if opencode_live and 'error' not in opencode_live:
            result['opencode']['_cost'] = opencode_live
        return result

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

    # --- Health / readiness / metrics ---
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        conn = _db_connect(DB_PATH)
        init_schema(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM collection_status WHERE ok=1")
        row = cursor.fetchone()
        conn.close()
        if row and row[0] > 0:
            return {"status": "ready"}
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    @app.get("/metrics")
    def get_metrics():
        conn = _db_connect(DB_PATH)
        init_schema(conn)
        result = metrics(conn)
        conn.close()
        return result

    # --- Static frontend ---
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def read_root():
        return RedirectResponse(url='/static/index.html')

    return app
