import sqlite3
import os
import os.path
import time
from datetime import datetime, timezone, timedelta

DB_PATH = os.getenv('USAGE_DB_PATH') or os.path.join(os.path.dirname(__file__), "usage.db")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'opencode',
            cycle_ts INTEGER DEFAULT 0,
            timestamp TEXT,
            sessions INTEGER,
            messages INTEGER,
            days INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0.0,
            avg_cost_per_day REAL DEFAULT 0.0,
            avg_tokens_per_session REAL DEFAULT 0.0,
            median_tokens_per_session REAL DEFAULT 0.0,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read INTEGER,
            cache_write INTEGER,
            UNIQUE(source, cycle_ts)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'opencode',
            cycle_ts INTEGER DEFAULT 0,
            timestamp TEXT,
            model_name TEXT NOT NULL,
            messages INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read INTEGER,
            cache_write INTEGER,
            cost REAL,
            UNIQUE(source, cycle_ts, model_name)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quota_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL DEFAULT 'agy',
            cycle_ts INTEGER DEFAULT 0,
            timestamp TEXT,
            model_group TEXT NOT NULL,
            limit_type TEXT NOT NULL,
            used REAL,
            total REAL,
            remaining_pct REAL,
            refreshes_in_seconds INTEGER,
            UNIQUE(source, cycle_ts, model_group, limit_type)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            cycle_ts INTEGER DEFAULT 0,
            timestamp TEXT,
            ok INTEGER NOT NULL,
            error TEXT,
            duration_ms REAL,
            UNIQUE(source, cycle_ts)
        )
    ''')

    # Create indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_usage_history_cycle_ts ON usage_history(cycle_ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_usage_cycle_ts ON model_usage(cycle_ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_snapshots_cycle_ts ON quota_snapshots(cycle_ts)')

    # Maintain indexes compatibility
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_usage_history_source_ts ON usage_history(source, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_usage_source_ts ON model_usage(source, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_snapshots_source_ts ON quota_snapshots(source, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_ts ON quota_snapshots(timestamp, model_group)')

    cursor.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ('schema_version', '1')
    )

    conn.commit()


def init_db():
    conn = connect(DB_PATH)
    init_schema(conn)
    conn.close()


def record_status(conn: sqlite3.Connection, source: str, *args, **kwargs) -> None:
    # Supports both:
    # 1. New: record_status(conn, source, cycle_ts, ok, error, duration_ms)
    # 2. Old: record_status(conn, source, ok, error, duration_ms)
    if len(args) >= 1 and isinstance(args[0], bool):
        ok = args[0]
        error = args[1] if len(args) > 1 else None
        duration_ms = args[2] if len(args) > 2 else 0.0
        now_sec = int(time.time())
        cycle_ts = (now_sec // 600) * 600
    elif len(args) >= 3:
        cycle_ts = args[0]
        ok = args[1]
        error = args[2]
        duration_ms = args[3] if len(args) > 3 else 0.0
    else:
        # Fallback keyword arguments
        cycle_ts = kwargs.get('cycle_ts')
        ok = kwargs.get('ok', True)
        error = kwargs.get('error') or kwargs.get('err')
        duration_ms = kwargs.get('duration_ms', 0.0)
        if cycle_ts is None:
            cycle_ts = (int(time.time()) // 600) * 600

    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    conn.execute('''
        INSERT OR REPLACE INTO collection_status (source, cycle_ts, timestamp, ok, error, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (source, cycle_ts, ts_str, 1 if ok else 0, error, duration_ms))
    conn.commit()


def metrics(conn: sqlite3.Connection) -> dict:
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM collection_status")
    sources = [r['source'] for r in cursor.fetchall()]

    per_source = {}
    for src in sources:
        cursor.execute(
            "SELECT timestamp, ok, error, duration_ms FROM collection_status "
            "WHERE source=? ORDER BY id DESC LIMIT 1",
            (src,)
        )
        row = cursor.fetchone()
        if row:
            per_source[src] = {
                'last_success_at': row['timestamp'] if row['ok'] else None,
                'last_error': None if row['ok'] else row['error'],
                'last_duration_ms': row['duration_ms'],
            }

    cursor.execute("SELECT COUNT(*) AS cnt FROM usage_history")
    total_polls = cursor.fetchone()['cnt']

    try:
        db_size_bytes = os.path.getsize(DB_PATH)
    except OSError:
        db_size_bytes = 0

    return {
        'per_source': per_source,
        'total_polls': total_polls,
        'db_size_bytes': db_size_bytes,
    }


def prune(conn: sqlite3.Connection, retention_days: int) -> None:
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_ts = int(cutoff_time.timestamp())
    cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')

    for table in ('usage_history', 'model_usage', 'quota_snapshots', 'collection_status'):
        # Delete by cycle_ts first
        conn.execute(f"DELETE FROM {table} WHERE cycle_ts < ?", (cutoff_ts,))
        # Fallback: delete by timestamp (for backwards-compatibility unit tests that don't write cycle_ts)
        conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff_str,))

    conn.commit()


def insert_usage(conn: sqlite3.Connection, source: str, *args, **kwargs) -> None:
    # Supports both:
    # 1. New: insert_usage(conn, source, cycle_ts, overview, models)
    # 2. Old compatibility wrapper: insert_usage(overview, cost_tokens, models, source='opencode')
    # Let's inspect the types
    if isinstance(conn, sqlite3.Connection):
        cycle_ts = args[0]
        overview = args[1]
        models = args[2]
    else:
        # Actually connect is called without conn. args[0]=overview, args[1]=cost_tokens, args[2]=models
        overview = conn
        cost_tokens = args[0] if len(args) > 0 else {}
        models = args[1] if len(args) > 1 else []
        source = kwargs.get('source', 'opencode')

        temp_conn = connect(DB_PATH)
        cycle_ts = (int(time.time()) // 600) * 600
        # Map old overview & cost_tokens
        sessions = overview.get('Sessions', 0)
        messages = overview.get('Messages', 0)
        input_tokens = cost_tokens.get('Input', 0)
        output_tokens = cost_tokens.get('Output', 0)
        cache_read = cost_tokens.get('Cache Read', 0)
        cache_write = cost_tokens.get('Cache Write', 0)

        _do_insert_usage(temp_conn, source, cycle_ts, sessions, messages, input_tokens, output_tokens, cache_read, cache_write, models)
        temp_conn.close()
        return

    # Extract overview parameters
    if hasattr(overview, 'sessions'):
        sessions = getattr(overview, 'sessions', 0)
        messages = getattr(overview, 'messages', 0)
        input_tokens = getattr(overview, 'input_tokens', 0)
        output_tokens = getattr(overview, 'output_tokens', 0)
        cache_read = getattr(overview, 'cache_read', 0)
        cache_write = getattr(overview, 'cache_write', 0)
    elif isinstance(overview, dict):
        sessions = overview.get('sessions', overview.get('Sessions', 0))
        messages = overview.get('messages', overview.get('Messages', 0))
        input_tokens = overview.get('input_tokens', overview.get('Input', 0))
        output_tokens = overview.get('output_tokens', overview.get('Output', 0))
        cache_read = overview.get('cache_read', overview.get('Cache Read', 0))
        cache_write = overview.get('cache_write', overview.get('Cache Write', 0))
    else:
        sessions = messages = input_tokens = output_tokens = cache_read = cache_write = 0

    _do_insert_usage(conn, source, cycle_ts, sessions, messages, input_tokens, output_tokens, cache_read, cache_write, models)


def _do_insert_usage(conn, source, cycle_ts, sessions, messages, input_tokens, output_tokens, cache_read, cache_write, models):
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    conn.execute('''
        INSERT OR REPLACE INTO usage_history (
            timestamp, source, cycle_ts, sessions, messages,
            input_tokens, output_tokens, cache_read, cache_write
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ts_str, source, cycle_ts, sessions, messages,
        input_tokens, output_tokens, cache_read, cache_write
    ))

    for m in models:
        if hasattr(m, 'model_name'):
            model_name = m.model_name
            m_messages = m.messages
            m_input_tokens = m.input_tokens
            m_output_tokens = m.output_tokens
            m_cache_read = m.cache_read
            m_cache_write = m.cache_write
            cost = m.cost
        elif isinstance(m, dict):
            model_name = m.get('name') or m.get('model_name')
            m_messages = m.get('Messages', m.get('messages', 0))
            m_input_tokens = m.get('Input Tokens', m.get('input_tokens', 0))
            m_output_tokens = m.get('Output Tokens', m.get('output_tokens', 0))
            m_cache_read = m.get('Cache Read', m.get('cache_read', 0))
            m_cache_write = m.get('Cache Write', m.get('cache_write', 0))
            cost = m.get('Cost', m.get('cost', 0.0))
        else:
            continue

        conn.execute('''
            INSERT OR REPLACE INTO model_usage (
                timestamp, source, cycle_ts, model_name, messages,
                input_tokens, output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ts_str, source, cycle_ts, model_name, m_messages,
            m_input_tokens, m_output_tokens, m_cache_read, m_cache_write, cost
        ))

    conn.commit()


def latest_usage(conn: sqlite3.Connection, source: str = None, cycle_ts: int = None, include_model_deltas: bool = False) -> dict:
    cursor = conn.cursor()
    result = {}
    sources = [source] if source is not None else ['opencode', 'agy', 'codex']

    for src in sources:
        if cycle_ts is not None:
            cursor.execute(
                "SELECT * FROM usage_history WHERE source=? AND cycle_ts=? LIMIT 1",
                (src, cycle_ts)
            )
        else:
            cursor.execute(
                "SELECT * FROM usage_history WHERE source=? ORDER BY cycle_ts DESC, timestamp DESC LIMIT 1",
                (src,)
            )
        row = cursor.fetchone()
        if not row:
            continue

        row_dict = dict(row)
        cursor.execute(
            "SELECT * FROM model_usage WHERE source=? AND cycle_ts=? ORDER BY input_tokens DESC",
            (src, row_dict['cycle_ts'])
        )
        row_dict['models'] = [dict(r) for r in cursor.fetchall()]

        if include_model_deltas:
            # Query the previous cycle_ts
            cursor.execute(
                "SELECT DISTINCT cycle_ts FROM usage_history WHERE source=? AND cycle_ts < ? ORDER BY cycle_ts DESC LIMIT 1",
                (src, row_dict['cycle_ts'])
            )
            prev_row = cursor.fetchone()
            if prev_row:
                prev_ts = prev_row['cycle_ts']
                cursor.execute(
                    "SELECT * FROM model_usage WHERE source=? AND cycle_ts=? ORDER BY input_tokens DESC",
                    (src, prev_ts)
                )
                prev_models = {m['model_name']: dict(m) for m in cursor.fetchall()}
                deltas = []
                for m in row_dict['models']:
                    prev = prev_models.get(m['model_name'], {})
                    delta = {
                        'model_name': m['model_name'],
                        'messages': m['messages'] - (prev.get('messages', 0) or 0),
                        'input_tokens': m['input_tokens'] - (prev.get('input_tokens', 0) or 0),
                        'output_tokens': m['output_tokens'] - (prev.get('output_tokens', 0) or 0),
                        'cost': m['cost'] - (prev.get('cost', 0.0) or 0.0),
                    }
                    deltas.append(delta)
                row_dict['model_deltas'] = deltas
            else:
                row_dict['model_deltas'] = []

        if source is not None:
            return {source: row_dict}
        result[src] = row_dict

    return result


def history(conn: sqlite3.Connection, source: str = None, range: str = None) -> list:
    cursor = conn.cursor()

    if source is None:
        # Aggregated history across all sources grouped by cycle_ts
        cursor.execute('''
            SELECT 
                cycle_ts,
                min(timestamp) as timestamp,
                SUM(sessions) as sessions,
                SUM(messages) as messages,
                SUM(input_tokens) as input_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(cache_read) as cache_read,
                SUM(cache_write) as cache_write
            FROM usage_history
            GROUP BY cycle_ts
            ORDER BY cycle_ts ASC
        ''')
        rows = [dict(r) for r in cursor.fetchall()]
        return rows

    cursor.execute('''
        SELECT * FROM usage_history
        WHERE source=?
        ORDER BY cycle_ts DESC
    ''', (source,))
    rows = [dict(r) for r in cursor.fetchall()]

    if rows:
        cycle_ts_list = tuple(r['cycle_ts'] for r in rows)
        placeholders = ','.join('?' for _ in cycle_ts_list)
        cursor.execute(f'''
            SELECT * FROM model_usage
            WHERE source=? AND cycle_ts IN ({placeholders})
            ORDER BY cycle_ts, input_tokens DESC
        ''', (source, *cycle_ts_list))
        model_rows = cursor.fetchall()

        models_by_cycle = {}
        for m in model_rows:
            cts = m['cycle_ts']
            if cts not in models_by_cycle:
                models_by_cycle[cts] = []
            models_by_cycle[cts].append(dict(m))

        for r in rows:
            r['models'] = models_by_cycle.get(r['cycle_ts'], [])

    return rows[::-1]


def insert_quota(conn: sqlite3.Connection, source: str, *args, **kwargs) -> None:
    # Supports both:
    # 1. New: insert_quota(conn, source, cycle_ts, rows)
    # 2. Old: insert_quota(quota_data, source='agy')
    if isinstance(conn, sqlite3.Connection):
        cycle_ts = args[0]
        data = args[1]
    else:
        quota_data = conn
        source = kwargs.get('source', 'agy')

        if 'error' in quota_data:
            return

        temp_conn = connect(DB_PATH)
        cycle_ts = (int(time.time()) // 600) * 600
        _do_insert_quota(temp_conn, source, cycle_ts, quota_data)
        temp_conn.close()
        return

    _do_insert_quota(conn, source, cycle_ts, data)


def _do_insert_quota(conn, source, cycle_ts, data):
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    if isinstance(data, dict):
        for key, val in data.items():
            if not isinstance(val, dict):
                continue
            for subkey, subval in val.items():
                if isinstance(subval, dict):
                    has_deep_nesting = False
                    for _, leaf in subval.items():
                        if isinstance(leaf, dict):
                            has_deep_nesting = True
                            break
                    if has_deep_nesting:
                        for limit_type, info in subval.items():
                            if isinstance(info, dict):
                                _save_quota_row(conn, ts_str, key, cycle_ts, subkey, limit_type, info)
                    else:
                        _save_quota_row(conn, ts_str, source, cycle_ts, key, subkey, subval)
    elif isinstance(data, list):
        for r in data:
            if not isinstance(r, dict):
                continue
            group_name = r.get('model_group')
            limit_type = r.get('limit_type')
            used = r.get('used', 0.0)
            total = r.get('total', 0.0)
            remaining_pct = r.get('remaining_pct', 0.0)
            refreshes_in = r.get('refreshes_in_seconds', r.get('refreshes_in', 0))

            conn.execute('''
                INSERT OR REPLACE INTO quota_snapshots (
                    timestamp, source, cycle_ts, model_group, limit_type,
                    used, total, remaining_pct, refreshes_in_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ts_str, source, cycle_ts, group_name, limit_type,
                used, total, remaining_pct, refreshes_in
            ))
    conn.commit()


def _save_quota_row(conn, ts_str, source, cycle_ts, group_name, limit_type, info):
    used = info.get('used', 0.0)
    total = info.get('total', 0.0)
    remaining_pct = info.get('remaining_pct', 0.0)
    refreshes_in = info.get('refreshes_in_seconds', info.get('refreshes_in', 0))

    conn.execute('''
        INSERT OR REPLACE INTO quota_snapshots (
            timestamp, source, cycle_ts, model_group, limit_type,
            used, total, remaining_pct, refreshes_in_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ts_str, source, cycle_ts, group_name, limit_type,
        used, total, remaining_pct, refreshes_in
    ))


def latest_quota(conn: sqlite3.Connection, source: str = None) -> dict:
    cursor = conn.cursor()
    result = {}
    sources = [source] if source is not None else ['opencode', 'agy', 'codex']

    for src in sources:
        cursor.execute(
            "SELECT DISTINCT cycle_ts FROM quota_snapshots WHERE source=? ORDER BY cycle_ts DESC LIMIT 1",
            (src,)
        )
        row = cursor.fetchone()
        if not row:
            continue
        cts = row['cycle_ts']
        cursor.execute(
            "SELECT * FROM quota_snapshots WHERE source=? AND cycle_ts=? ORDER BY model_group, limit_type",
            (src, cts)
        )
        if src not in result:
            result[src] = {}
        for r in cursor.fetchall():
            group = r['model_group']
            if group not in result[src]:
                result[src][group] = {}
            result[src][group][r['limit_type']] = dict(r)

    if source is not None:
        return result
    return result


# --- Backward Compatibility Delegates ---
def get_latest_usage(source=None, include_model_deltas=False):
    conn = connect(DB_PATH)
    try:
        return latest_usage(conn, source, include_model_deltas=include_model_deltas)
    finally:
        conn.close()


def get_history_series(source='opencode'):
    conn = connect(DB_PATH)
    try:
        return history(conn, source)
    finally:
        conn.close()


def get_latest_quota(source=None):
    conn = connect(DB_PATH)
    try:
        return latest_quota(conn, source)
    finally:
        conn.close()

