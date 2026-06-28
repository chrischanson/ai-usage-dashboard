import sqlite3
import os
import os.path
from datetime import datetime, timedelta

DB_PATH = os.getenv('AQM_DB_PATH') or os.path.join(os.path.dirname(__file__), "agy_quota.db")


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
        CREATE TABLE IF NOT EXISTS usage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'opencode',
            sessions INTEGER,
            messages INTEGER,
            days INTEGER,
            total_cost REAL,
            avg_cost_per_day REAL,
            avg_tokens_per_session REAL,
            median_tokens_per_session REAL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read INTEGER,
            cache_write INTEGER
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS model_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'opencode',
            model_name TEXT,
            messages INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read INTEGER,
            cache_write INTEGER,
            cost REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quota_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'agy',
            model_group TEXT,
            limit_type TEXT,
            used REAL,
            total REAL,
            remaining_pct REAL,
            refreshes_in_seconds INTEGER
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            ok INTEGER NOT NULL,
            error TEXT,
            duration_ms REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_usage_history_source_ts
        ON usage_history(source, timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_model_usage_source_ts
        ON model_usage(source, timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_quota_snapshots_source_ts
        ON quota_snapshots(source, timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_quota_ts
        ON quota_snapshots(timestamp, model_group)
    ''')

    cursor.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ('schema_version', '1')
    )

    # Migrate existing table if needed
    try:
        cursor.execute("ALTER TABLE quota_snapshots ADD COLUMN source TEXT DEFAULT 'agy'")
    except sqlite3.OperationalError:
        pass

    conn.commit()


def record_status(
    conn: sqlite3.Connection,
    source: str,
    ok: bool,
    error: str,
    duration_ms: float,
) -> None:
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        "INSERT INTO collection_status (source, timestamp, ok, error, duration_ms) "
        "VALUES (?, ?, ?, ?, ?)",
        (source, ts, 1 if ok else 0, error, duration_ms)
    )
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

    db_path = getattr(conn, 'db_path', None) or (
        os.path.join(os.path.dirname(__file__), 'agy_quota.db')
    )
    try:
        db_size_bytes = os.path.getsize(db_path)
    except OSError:
        db_size_bytes = 0

    return {
        'per_source': per_source,
        'total_polls': total_polls,
        'db_size_bytes': db_size_bytes,
    }


def prune(conn: sqlite3.Connection, retention_days: int) -> None:
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).strftime('%Y-%m-%d %H:%M:%S')
    for table in ('usage_history', 'model_usage', 'quota_snapshots', 'collection_status'):
        conn.execute(f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,))
    conn.commit()


def init_db():
    conn = connect(DB_PATH)
    init_schema(conn)
    conn.close()


def insert_usage(overview, cost_tokens, models, source='opencode'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
        INSERT INTO usage_history (
            timestamp, source, sessions, messages, days, total_cost, avg_cost_per_day,
            avg_tokens_per_session, median_tokens_per_session,
            input_tokens, output_tokens, cache_read, cache_write
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ts,
        source,
        overview.get('Sessions', 0),
        overview.get('Messages', 0),
        overview.get('Days', 0),
        cost_tokens.get('Total Cost', 0.0),
        cost_tokens.get('Avg Cost/Day', 0.0),
        cost_tokens.get('Avg Tokens/Session', 0.0),
        cost_tokens.get('Median Tokens/Session', 0.0),
        cost_tokens.get('Input', 0),
        cost_tokens.get('Output', 0),
        cost_tokens.get('Cache Read', 0),
        cost_tokens.get('Cache Write', 0),
    ))

    for m in models:
        cursor.execute('''
            INSERT INTO model_usage (
                timestamp, source, model_name, messages, input_tokens,
                output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ts,
            source,
            m['name'],
            m.get('Messages', 0),
            m.get('Input Tokens', 0),
            m.get('Output Tokens', 0),
            m.get('Cache Read', 0),
            m.get('Cache Write', 0),
            m.get('Cost', 0.0),
        ))

    conn.commit()
    conn.close()


def get_latest_usage(source=None, include_model_deltas=False):
    """Return the latest usage snapshot. If source is None, returns both sources merged."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    result = {}
    for src in (['opencode', 'agy', 'codex'] if source is None else [source]):
        cursor.execute(
            "SELECT * FROM usage_history WHERE source=? ORDER BY timestamp DESC LIMIT 1",
            (src,)
        )
        row = cursor.fetchone()
        if not row:
            continue
        row_dict = dict(row)
        cursor.execute(
            "SELECT * FROM model_usage WHERE source=? AND timestamp=? ORDER BY input_tokens DESC",
            (src, row_dict['timestamp'])
        )
        row_dict['models'] = [dict(r) for r in cursor.fetchall()]

        if include_model_deltas:
            cursor.execute(
                "SELECT DISTINCT timestamp FROM usage_history WHERE source=? ORDER BY timestamp DESC LIMIT 2 OFFSET 1",
                (src,)
            )
            prev_row = cursor.fetchone()
            if prev_row:
                prev_ts = prev_row['timestamp']
                cursor.execute(
                    "SELECT * FROM model_usage WHERE source=? AND timestamp=? ORDER BY input_tokens DESC",
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
                        'cost': m['cost'] - (prev.get('cost', 0) or 0),
                    }
                    deltas.append(delta)
                row_dict['model_deltas'] = deltas

        result[src] = row_dict

    conn.close()
    return result


def get_history_series(source='opencode', limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM usage_history WHERE source=? ORDER BY timestamp DESC LIMIT ?",
        (source, limit)
    )
    rows = [dict(r) for r in cursor.fetchall()]
    # Attach models per entry
    if rows:
        timestamps = tuple(r['timestamp'] for r in rows)
        placeholders = ','.join('?' for _ in timestamps)
        cursor.execute(
            f"SELECT * FROM model_usage WHERE source=? AND timestamp IN ({placeholders}) ORDER BY timestamp, input_tokens DESC",
            (source, *timestamps)
        )
        model_rows = cursor.fetchall()
        models_by_ts = {}
        for m in model_rows:
            ts = m['timestamp']
            if ts not in models_by_ts:
                models_by_ts[ts] = []
            models_by_ts[ts].append(dict(m))
        for r in rows:
            r['models'] = models_by_ts.get(r['timestamp'], [])
    conn.close()
    return rows[::-1]


def insert_quota(quota_data: dict, source='agy'):
    """Insert a quota snapshot."""
    if 'error' in quota_data:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    for group_name, limits in quota_data.items():
        if not isinstance(limits, dict):
            continue
        for limit_type, info in limits.items():
            if not isinstance(info, dict):
                continue
            cursor.execute('''
                INSERT INTO quota_snapshots
                    (timestamp, source, model_group, limit_type, used, total,
                     remaining_pct, refreshes_in_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                ts,
                source,
                group_name,
                limit_type,
                info.get('used', 0),
                info.get('total', 0),
                info.get('remaining_pct', 0),
                info.get('refreshes_in', 0),
            ))
    conn.commit()
    conn.close()


def get_latest_quota(source=None):
    """Return all quota limits from the latest snapshot per source.
    If source is None, merges latest data from each source."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if source:
        cursor.execute(
            "SELECT DISTINCT timestamp FROM quota_snapshots WHERE source=? ORDER BY timestamp DESC LIMIT 1",
            (source,)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {}
        ts = row['timestamp']
        cursor.execute(
            "SELECT * FROM quota_snapshots WHERE timestamp=? AND source=? ORDER BY model_group, limit_type",
            (ts, source)
        )
    else:
        cursor.execute("SELECT DISTINCT source FROM quota_snapshots")
        sources = [r[0] for r in cursor.fetchall()]
        result = {}
        for src in sources:
            cursor.execute(
                "SELECT DISTINCT timestamp FROM quota_snapshots WHERE source=? ORDER BY timestamp DESC LIMIT 1",
                (src,)
            )
            row = cursor.fetchone()
            if not row:
                continue
            ts = row['timestamp']
            cursor.execute(
                "SELECT * FROM quota_snapshots WHERE timestamp=? AND source=? ORDER BY model_group, limit_type",
                (ts, src)
            )
            if src not in result:
                result[src] = {}
            for r in cursor.fetchall():
                group = r['model_group']
                if group not in result[src]:
                    result[src][group] = {}
                result[src][group][r['limit_type']] = dict(r)
        conn.close()
        return result

    result = {}
    for r in cursor.fetchall():
        src = r['source']
        if src not in result:
            result[src] = {}
        group = r['model_group']
        if group not in result[src]:
            result[src][group] = {}
        result[src][group][r['limit_type']] = dict(r)
    conn.close()
    return result
