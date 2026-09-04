"""FastAPI app factory for the AI Usage Dashboard."""
import os
import threading
import time
from fastapi import FastAPI, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse

from db import latest_usage, history, latest_quota, metrics
from db import connect as _db_connect, DB_PATH, init_schema
from util import parse_iso_seconds
from source_registry import get_all_names, is_valid_source


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


# How stale a persisted snapshot may be before the UI should say so. Three
# poll intervals: one missed cycle is normal jitter, three is a real problem.
_STALE_AFTER_SECONDS = 1800


def _is_live_result(raw) -> bool:
    """True only for a fetch that actually produced quota data.

    A hard `error` is a failure. So is `quota_error`, which means the plan was
    readable but the quota read itself failed -- useful to display, but not a
    successful live reading and never cacheable as one.
    """
    if not isinstance(raw, dict) or not raw:
        return False
    return 'error' not in raw and 'quota_error' not in raw


def _get_cached_quota(source: str, fetcher, force: bool = False):
    """Fetch a source's raw quota, memoized for _QUOTA_TTL_SECONDS.

    Returns `(raw, live)`. A failed fetch is never written to the cache: doing
    so would pin an error in front of good data for the whole TTL, and would
    make the next forced refresh a no-op.
    """
    now = time.time()
    cached = _quota_cache.get(source)
    if not force and cached and (now - cached[0]) < _QUOTA_TTL_SECONDS:
        return cached[1], True

    # Cache stampede guard: on expiry, every concurrent request for this
    # source would otherwise run the (slow: subprocess/network) fetcher and
    # block for tens of seconds. Only the first thread through the lock
    # fetches; the rest wait and then re-read the now-fresh cache.
    lock = _lock_for(source)
    with lock:
        cached = _quota_cache.get(source)
        if not force and cached and (time.time() - cached[0]) < _QUOTA_TTL_SECONDS:
            return cached[1], True
        try:
            raw = fetcher()
        except Exception:
            raw = None
        if raw is None:
            raw = {'error': 'fetch failed'}
        if _is_live_result(raw):
            _quota_cache[source] = (time.time(), raw)
            return raw, True
        return raw, False


def _error_category(raw) -> str | None:
    """The collector's own safe failure category, if it supplied one."""
    if not isinstance(raw, dict):
        return None
    category = raw.get('error_category')
    if category:
        return str(category)
    if 'error' in raw or 'quota_error' in raw:
        return 'unavailable'
    return None


def _persist_forced_quota(source: str, normalized: dict) -> None:
    """Store a manually forced reading so it survives the next page load.

    Best-effort: a write failure here must not turn a successful live read
    into an API error, since the caller already has the data in hand.
    """
    try:
        from db import record_quota
        from config import load_config
        # Snap to the poller's cycle grid so a forced read updates the current
        # cycle's row instead of littering quota_snapshots with off-grid ones.
        interval = max(1, load_config().poll_interval)
        cycle_ts = (int(time.time()) // interval) * interval
        conn = _db_connect(DB_PATH)
        try:
            record_quota(conn, source, cycle_ts, normalized)
        finally:
            conn.close()
    except Exception:
        pass


def _observed_at(source_data) -> int:
    """Newest cycle_ts among a stored source's limit rows, or 0."""
    newest = 0
    if not isinstance(source_data, dict):
        return newest
    for key, group in source_data.items():
        if isinstance(key, str) and key.startswith('_'):
            continue
        if not isinstance(group, dict):
            continue
        for row in group.values():
            if isinstance(row, dict):
                try:
                    newest = max(newest, int(row.get('cycle_ts') or 0))
                except (TypeError, ValueError):
                    continue
    return newest


def _annotate(source_data: dict, live: bool, error_category: str = None) -> dict:
    """Attach the freshness envelope the frontend uses to explain a card.

    Kept under an underscore-prefixed key so it travels with the source it
    describes without being mistaken for a quota group. Renderers and the DB
    writer both skip `_`-prefixed keys.
    """
    if not isinstance(source_data, dict):
        return source_data
    # A live reading was observed now; a stored one carries its cycle.
    observed_at = int(time.time()) if live else _observed_at(source_data)
    age = max(0, int(time.time()) - observed_at) if observed_at else None
    status = {
        'live': bool(live),
        'observed_at': observed_at or None,
        'age_seconds': age,
        'stale': bool(not live and (age is None or age > _STALE_AFTER_SECONDS)),
    }
    if error_category:
        status['error_category'] = error_category
    source_data['_status'] = status
    return source_data


_RANGE_SECONDS = {
    '1h': 3600,
    '6h': 21600,
    '1d': 86400,
    '1w': 604800,
    '1m': 2592000,
    '3m': 7776000,
}


def _resolve_start_ts(conn, range_str: str, source: str = None) -> int | None:
    if range_str == 'all':
        return None
    duration = _RANGE_SECONDS.get(range_str)
    if not duration:
        return None
    cursor = conn.cursor()
    if source:
        cursor.execute("SELECT MAX(cycle_ts) FROM usage_history WHERE source=?", (source,))
    else:
        cursor.execute("SELECT MAX(cycle_ts) FROM usage_history")
    row = cursor.fetchone()
    max_ts = row[0] if row else None
    return (max_ts - duration) if max_ts else None


def create_app() -> FastAPI:
    app = FastAPI(title="Model Usage Dashboard API", docs_url=None, redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1024)

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
        if request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        return response

    async def not_found(request, exc):
        return error_response("not_found", "The requested resource was not found", 404)

    async def internal_error(request, exc):
        return error_response("internal", "An unexpected error occurred", 500)

    app.add_exception_handler(404, not_found)
    app.add_exception_handler(500, internal_error)

    @app.get("/api/sources")
    def api_sources():
        from source_registry import get_all_sources
        return [
            {
                "name": entry.name,
                "display_name": entry.display_name,
                "color": getattr(entry, 'color', None),
                "has_quota": getattr(entry, 'has_quota', bool(entry.quota_collector)),
            }
            for entry in get_all_sources().values()
        ]

    def _cadence_meta(result: dict) -> dict:
        """Read-only cadence facts for the header's cycle strip.

        Additive and derived: the newest cycle_ts already present in `result`
        plus the configured poll interval. Nothing here changes what is polled
        or stored. Keyed under `_meta` so it can never collide with a source
        name (sources are the only other top-level keys).
        """
        from config import load_config
        interval = load_config().poll_interval
        cycles = [row.get('cycle_ts') for row in result.values()
                  if isinstance(row, dict) and row.get('cycle_ts')]
        latest = max(cycles) if cycles else None
        return {
            "poll_interval_s": interval,
            "latest_cycle_ts": latest,
            "next_cycle_ts": (latest + interval) if latest else None,
        }

    @app.get("/api/usage/latest")
    def api_usage_latest(deltas: bool = Query(False)):
        conn = _db_connect(DB_PATH)
        try:
            result = latest_usage(conn, include_model_deltas=deltas)
        finally:
            conn.close()
        result['_meta'] = _cadence_meta(result)
        return result

    @app.get("/api/usage/{source}/latest")
    def api_usage_source_latest(source: str):
        if not is_valid_source(source):
            return error_response("source_unknown", f"Unknown source: {source}", 404)

        conn = _db_connect(DB_PATH)
        try:
            result = latest_usage(conn, source=source)
        finally:
            conn.close()
        result['_meta'] = _cadence_meta(result)
        return result

    @app.get("/api/usage/{source}/history")
    def api_usage_source_history(source: str, range: str = Query('all'), with_models: bool = Query(None)):
        if not is_valid_source(source):
            return error_response("source_unknown", f"Unknown source: {source}", 404)
        if with_models is None:
            with_models = (range != 'all')

        conn = _db_connect(DB_PATH)
        try:
            start_ts = _resolve_start_ts(conn, range, source=source)
            return history(conn, source=source, with_models=with_models, start_ts=start_ts)
        finally:
            conn.close()

    @app.get("/api/usage/history")
    def api_history(range: str = Query('all'), with_models: bool = Query(None)):
        if with_models is None:
            with_models = (range != 'all')

        conn = _db_connect(DB_PATH)
        try:
            start_ts = _resolve_start_ts(conn, range, source=None)
            return history(conn, source=None, with_models=with_models, start_ts=start_ts)
        finally:
            conn.close()

    @app.get("/api/quota/latest")
    def api_quota_latest(force: bool = False):
        conn = _db_connect(DB_PATH)
        try:
            result = latest_quota(conn)
        finally:
            conn.close()

        if force:
            from source_registry import get_all_sources
            from concurrent.futures import ThreadPoolExecutor
            sources = get_all_sources()
            with ThreadPoolExecutor(max_workers=len(sources)) as executor:
                futures = {
                    src: executor.submit(_get_cached_quota, src, entry.quota_collector, True)
                    for src, entry in sources.items() if entry.quota_collector
                }
                for src, fut in futures.items():
                    raw, live = fut.result()
                    entry = sources[src]
                    norm = entry.quota_normalizer(raw) if (entry and entry.quota_normalizer and raw) else None
                    # A failed refresh must never replace good persisted data
                    # with an empty object; the stored snapshot stands, marked
                    # stale, so the card degrades instead of blanking.
                    if norm and live:
                        result[src] = norm
                        _annotate(result[src], True)
                    elif src in result:
                        _annotate(result[src], False, _error_category(raw))
        for src, data in result.items():
            if isinstance(data, dict) and '_status' not in data:
                _annotate(data, False)
        return result

    @app.get("/api/quota/{source}/latest")
    def api_quota_source_latest(source: str, force: bool = False):
        if not is_valid_source(source):
            return error_response("source_unknown", f"Unknown source: {source}", 404)

        conn = _db_connect(DB_PATH)
        try:
            db_result = latest_quota(conn, source=source)
        finally:
            conn.close()

        if force:
            from source_registry import get_source
            entry = get_source(source)
            if entry and entry.quota_collector:
                raw, live = _get_cached_quota(source, entry.quota_collector, True)
                norm = entry.quota_normalizer(raw) if (entry.quota_normalizer and raw) else None
                if norm and live:
                    # Persist through the same validation path the poller uses,
                    # so the next ordinary page load does not visibly revert to
                    # the older snapshot.
                    _persist_forced_quota(source, norm)
                    return {source: _annotate(norm, True)}
                # Refresh failed: hand back the last good snapshot, labelled.
                if db_result.get(source):
                    return {source: _annotate(db_result[source], False, _error_category(raw))}
                return {source: _annotate({}, False, _error_category(raw))}

        if db_result.get(source):
            _annotate(db_result[source], False)
        return db_result or {}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        conn = _db_connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM collection_status WHERE ok=1")
            row = cursor.fetchone()
            if row and row[0] > 0:
                return {"status": "ready"}
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        finally:
            conn.close()

    @app.get("/metrics")
    def get_metrics():
        from integrity import check_integrity
        from config import load_config
        conn = _db_connect(DB_PATH)
        try:
            result = metrics(conn)
            cfg = load_config()
            since_cycle = int(time.time()) - 2 * 86400
            result['integrity'] = check_integrity(conn, cfg.poll_interval, since_cycle=since_cycle)
            return result
        finally:
            conn.close()

    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/")
    def read_root():
        return RedirectResponse(url='/static/index.html')

    return app
