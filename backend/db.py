"""SQLite layer for the AI Usage Dashboard.

Data model (schema v3): the database stores *raw observations only*.

- usage_history / model_usage hold, per (source, cycle_ts), the lifetime
  counters exactly as each parser reported them. Parsers read local tool
  state (Codex's threads table, AGY's conversation DBs, opencode's stats
  command, Claude's transcripts), which is a machine-wide lifetime record —
  not scoped to when this dashboard started watching.
- Everything displayed is derived at read time: the per-cycle delta is
  max(0, raw - previous raw) and the cumulative total is the running sum of
  those deltas. The first observation of a source contributes zero, so a
  tool's pre-existing history never shows up as a giant new event.

Storing raw readings instead of accumulated totals means a bad row corrupts
only its own delta (not every row after it), and history can always be
re-derived or audited against the tools themselves.
"""
import os
import os.path
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH = os.getenv('USAGE_DB_PATH') or os.path.join(os.path.dirname(__file__), "usage.db")

_USAGE_FIELDS = ('sessions', 'messages', 'input_tokens', 'output_tokens', 'cache_read', 'cache_write')
_MODEL_FIELDS = ('messages', 'input_tokens', 'output_tokens', 'cache_read', 'cache_write')


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
            kind TEXT NOT NULL DEFAULT 'usage',
            cycle_ts INTEGER DEFAULT 0,
            timestamp TEXT,
            ok INTEGER NOT NULL,
            error TEXT,
            duration_ms REAL,
            UNIQUE(source, kind, cycle_ts)
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_usage_history_cycle_ts ON usage_history(cycle_ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_usage_cycle_ts ON model_usage(cycle_ts)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_quota_snapshots_cycle_ts ON quota_snapshots(cycle_ts)')

    cursor.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
        ('schema_version', '3')
    )

    conn.commit()
    _migrate_schema(conn)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply incremental schema migrations for existing databases."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM meta WHERE key='schema_version'")
    row = cursor.fetchone()
    version = int(row['value']) if row else 0

    if version < 2:
        # Add 'kind' column and fix UNIQUE constraint.
        # SQLite cannot ALTER TABLE to drop constraints, so we recreate the table.
        cursor.execute("PRAGMA table_info(collection_status)")
        columns = {r[1] for r in cursor.fetchall()}
        if 'kind' not in columns:
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute('''
                CREATE TABLE collection_status_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'usage',
                    cycle_ts INTEGER DEFAULT 0,
                    timestamp TEXT,
                    ok INTEGER NOT NULL,
                    error TEXT,
                    duration_ms REAL,
                    UNIQUE(source, kind, cycle_ts)
                )
            ''')
            cursor.execute('''
                INSERT INTO collection_status_new (id, source, kind, cycle_ts, timestamp, ok, error, duration_ms)
                SELECT id, source, 'usage', cycle_ts, timestamp, ok, error, duration_ms FROM collection_status
            ''')
            cursor.execute("DROP TABLE collection_status")
            cursor.execute("ALTER TABLE collection_status_new RENAME TO collection_status")
            cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '2')")
        conn.commit()
        version = 2

    # v3 is detected by introspection, not by trusting the version number:
    # any connection may have stamped meta before the migration ran (e.g. a
    # fresh init_schema on an old file), so the presence of the v2 artifacts
    # themselves is what triggers — and re-running on a migrated DB is a no-op.
    cursor.execute("PRAGMA table_info(usage_history)")
    dead_columns = 'total_cost' in {r[1] for r in cursor.fetchall()}
    if (version < 3 or dead_columns
            or _table_exists(cursor, 'source_baselines')
            or _table_exists(cursor, 'model_baselines')):
        _migrate_to_v3(conn)


def _table_exists(cursor, name: str) -> bool:
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cursor.fetchone() is not None


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """v2 stored *accumulated* totals in usage_history/model_usage, tracking
    each parser's last raw reading in source_baselines/model_baselines. v3
    stores the raw readings themselves and derives totals at read time.

    Conversion: shift each source's stored series by a constant so its last
    row equals the last raw reading recorded in the baselines. A uniform
    per-source shift preserves every delta (and therefore every derived
    total), while landing the series in raw space so the next poll's raw
    reading continues it seamlessly. Rows written before delta tracking
    existed were raw readings already (no baseline row -> shift of zero).
    """
    cursor = conn.cursor()

    # Back up the database file before a destructive migration.
    cursor.execute("PRAGMA database_list")
    db_file = cursor.fetchone()[2]
    if db_file and os.path.exists(db_file):
        backup = db_file + '.pre-v3.bak'
        if not os.path.exists(backup):
            shutil.copy2(db_file, backup)

    if _table_exists(cursor, 'source_baselines'):
        cursor.execute("SELECT * FROM source_baselines")
        for baseline in cursor.fetchall():
            src = baseline['source']
            cursor.execute(
                "SELECT * FROM usage_history WHERE source=? ORDER BY cycle_ts DESC LIMIT 1", (src,))
            last = cursor.fetchone()
            if not last:
                continue
            sets = ', '.join(f"{f} = {f} + ?" for f in _USAGE_FIELDS)
            offsets = [(baseline[f] or 0) - (last[f] or 0) for f in _USAGE_FIELDS]
            cursor.execute(f"UPDATE usage_history SET {sets} WHERE source=?", offsets + [src])
        cursor.execute("DROP TABLE source_baselines")

    if _table_exists(cursor, 'model_baselines'):
        cursor.execute("SELECT * FROM model_baselines")
        for baseline in cursor.fetchall():
            src, model = baseline['source'], baseline['model_name']
            cursor.execute(
                "SELECT * FROM model_usage WHERE source=? AND model_name=? ORDER BY cycle_ts DESC LIMIT 1",
                (src, model))
            last = cursor.fetchone()
            if not last:
                continue
            sets = ', '.join(f"{f} = {f} + ?" for f in _MODEL_FIELDS)
            offsets = [(baseline[f] or 0) - (last[f] or 0) for f in _MODEL_FIELDS]
            cursor.execute(
                f"UPDATE model_usage SET {sets} WHERE source=? AND model_name=?",
                offsets + [src, model])
        cursor.execute("DROP TABLE model_baselines")

    # Rebuild usage_history without the long-dead derived columns
    # (days, total_cost, avg_cost_per_day, avg_tokens_per_session, median_tokens_per_session).
    cursor.execute("PRAGMA table_info(usage_history)")
    columns = {r[1] for r in cursor.fetchall()}
    if 'total_cost' in columns:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute('''
            CREATE TABLE usage_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'opencode',
                cycle_ts INTEGER DEFAULT 0,
                timestamp TEXT,
                sessions INTEGER,
                messages INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_read INTEGER,
                cache_write INTEGER,
                UNIQUE(source, cycle_ts)
            )
        ''')
        cursor.execute('''
            INSERT INTO usage_history_new (id, source, cycle_ts, timestamp, sessions, messages,
                                           input_tokens, output_tokens, cache_read, cache_write)
            SELECT id, source, cycle_ts, timestamp, sessions, messages,
                   input_tokens, output_tokens, cache_read, cache_write
            FROM usage_history
        ''')
        cursor.execute("DROP TABLE usage_history")
        cursor.execute("ALTER TABLE usage_history_new RENAME TO usage_history")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_usage_history_cycle_ts ON usage_history(cycle_ts)')
        cursor.execute("PRAGMA foreign_keys=ON")

    # Backfill the status-pairing invariant for legacy rows written before
    # the write layer enforced it.
    cursor.execute('''
        INSERT OR IGNORE INTO collection_status (source, kind, cycle_ts, timestamp, ok, error, duration_ms)
        SELECT source, 'usage', cycle_ts, timestamp, 1, NULL, 0.0 FROM usage_history
    ''')

    # Cycles up to this point predate raw-observation storage; integrity
    # checks that assume clean raw data (monotonicity, model sums) skip them.
    cursor.execute("SELECT MAX(cycle_ts) FROM usage_history")
    newest = cursor.fetchone()[0] or 0
    cursor.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('v3_migrated_after_cycle', ?)",
        (str(newest),))

    cursor.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3')")
    conn.commit()


def init_db():
    conn = connect(DB_PATH)
    init_schema(conn)
    conn.close()


# --- Writers (the poller is the only intended caller) ---

def record_observation(conn: sqlite3.Connection, source: str, cycle_ts: int, result) -> None:
    """Store a parser's raw reading verbatim. `result` is a ParserResult
    (or anything with the same attributes)."""
    _do_insert_usage(conn, source, cycle_ts,
                     result.sessions, result.messages,
                     result.input_tokens, result.output_tokens,
                     result.cache_read, result.cache_write,
                     result.models)


def record_quota(conn: sqlite3.Connection, source: str, cycle_ts: int, data) -> None:
    _do_insert_quota(conn, source, cycle_ts, data)


def record_status(conn: sqlite3.Connection, source: str, kind: str, cycle_ts: int,
                  ok: bool, error: str | None, duration_ms: float = 0.0) -> None:
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    conn.execute('''
        INSERT OR REPLACE INTO collection_status (source, kind, cycle_ts, timestamp, ok, error, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (source, kind, cycle_ts, ts_str, 1 if ok else 0, error, duration_ms))
    conn.commit()


def _model_to_dict(m) -> dict | None:
    if hasattr(m, 'model_name'):
        return {
            'model_name': m.model_name, 'messages': m.messages,
            'input_tokens': m.input_tokens, 'output_tokens': m.output_tokens,
            'cache_read': m.cache_read, 'cache_write': m.cache_write, 'cost': m.cost,
        }
    if isinstance(m, dict):
        name = m.get('name') or m.get('model_name')
        if not name:
            return None
        return {
            'model_name': name,
            'messages': m.get('Messages', m.get('messages', 0)),
            'input_tokens': m.get('Input Tokens', m.get('input_tokens', 0)),
            'output_tokens': m.get('Output Tokens', m.get('output_tokens', 0)),
            'cache_read': m.get('Cache Read', m.get('cache_read', 0)),
            'cache_write': m.get('Cache Write', m.get('cache_write', 0)),
            'cost': m.get('Cost', m.get('cost', 0.0)),
        }
    return None


def _do_insert_usage(conn, source, cycle_ts, sessions, messages, input_tokens, output_tokens, cache_read, cache_write, models):
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    conn.execute('''
        INSERT OR REPLACE INTO usage_history (
            timestamp, source, cycle_ts, sessions, messages,
            input_tokens, output_tokens, cache_read, cache_write
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        ts_str, source, cycle_ts, sessions or 0, messages or 0,
        input_tokens or 0, output_tokens or 0, cache_read or 0, cache_write or 0
    ))

    for m in models or []:
        md = _model_to_dict(m)
        if md is None:
            continue
        conn.execute('''
            INSERT OR REPLACE INTO model_usage (
                timestamp, source, cycle_ts, model_name, messages,
                input_tokens, output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ts_str, source, cycle_ts, md['model_name'], md['messages'],
            md['input_tokens'], md['output_tokens'], md['cache_read'],
            md['cache_write'], md['cost']
        ))

    # Invariant: every usage_history write is paired with a collection_status
    # row, enforced here (not by caller discipline) so no future caller —
    # poller, test, or one-off script — can silently create ungoverned data.
    # A caller with real timing info (e.g. the poller) may overwrite this
    # afterwards via record_status(); that's an idempotent no-op otherwise.
    conn.execute('''
        INSERT OR REPLACE INTO collection_status (source, kind, cycle_ts, timestamp, ok, error, duration_ms)
        VALUES (?, 'usage', ?, ?, 1, NULL, 0.0)
    ''', (source, cycle_ts, ts_str))

    conn.commit()


# --- Read-time derivation ---

def _derive_usage_rows(rows: list, last_only: bool = False) -> list:
    """Convert raw observation rows (one source, ascending cycle_ts) into
    display rows: each _USAGE_FIELDS key becomes the cumulative total since
    the first observation, and delta_<field> holds the per-cycle increment.
    A raw counter decrease (tool reinstalled/reset) clamps that delta to 0
    and self-heals on the next cycle.

    The running totals inherently need the full series (the clamp means the
    total is not just last - first), but with last_only=True only the final
    row is materialized as a dict — earlier rows contribute their deltas and
    nothing else."""
    out = []
    prev_raw = None
    totals = {f: 0 for f in _USAGE_FIELDS}
    last_index = len(rows) - 1
    for i, r in enumerate(rows):
        raw = {f: (r[f] or 0) for f in _USAGE_FIELDS}
        deltas = {}
        for f in _USAGE_FIELDS:
            delta = 0 if prev_raw is None else max(0, raw[f] - prev_raw[f])
            totals[f] += delta
            deltas[f] = delta
        prev_raw = raw
        if last_only and i != last_index:
            continue
        d = dict(r)
        for f in _USAGE_FIELDS:
            d[f] = totals[f]
            d[f'delta_{f}'] = deltas[f]
        out.append(d)
    return out


def _derive_model_rows(model_rows: list, only_cycle: int = None) -> dict:
    """Same derivation per (model_name), for one source's model_usage rows in
    ascending cycle_ts order. Returns {cycle_ts: [derived model dicts]};
    with only_cycle set, only that cycle's dicts are built (the walk still
    covers every row, which the running totals require)."""
    prev_raw = {}
    totals = {}
    by_cycle: dict = {}
    for r in model_rows:
        name = r['model_name']
        raw = {f: (r[f] or 0) for f in _MODEL_FIELDS}
        tot = totals.setdefault(name, {f: 0 for f in _MODEL_FIELDS})
        prev = prev_raw.get(name)
        deltas = {}
        for f in _MODEL_FIELDS:
            delta = 0 if prev is None else max(0, raw[f] - prev[f])
            tot[f] += delta
            deltas[f] = delta
        prev_raw[name] = raw
        if only_cycle is not None and r['cycle_ts'] != only_cycle:
            continue
        d = dict(r)
        for f in _MODEL_FIELDS:
            d[f] = tot[f]
            d[f'delta_{f}'] = deltas[f]
        by_cycle.setdefault(r['cycle_ts'], []).append(d)
    return by_cycle


def _derived_source_history(conn: sqlite3.Connection, source: str, with_models: bool = True,
                            latest_only: bool = False) -> list:
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usage_history WHERE source=? ORDER BY cycle_ts ASC', (source,))
    rows = _derive_usage_rows(cursor.fetchall(), last_only=latest_only)
    if rows and with_models:
        cursor.execute(
            'SELECT * FROM model_usage WHERE source=? ORDER BY cycle_ts ASC, model_name ASC',
            (source,))
        only_cycle = rows[-1]['cycle_ts'] if latest_only else None
        models_by_cycle = _derive_model_rows(cursor.fetchall(), only_cycle=only_cycle)
        for r in rows:
            models = models_by_cycle.get(r['cycle_ts'], [])
            r['models'] = sorted(models, key=lambda m: m['input_tokens'], reverse=True)
    return rows


# latest_usage() is hit on every dashboard refresh but its answer only
# changes when the poller writes (every poll_interval). Cache the derived
# latest row per (db file, source), validated against a cheap fingerprint:
# row counts catch inserts and prune deletions; the newest raw row catches a
# same-cycle INSERT OR REPLACE (poller restart within one interval), which
# leaves count and MAX(cycle_ts) unchanged. In-memory databases are never
# cached — distinct :memory: connections are indistinguishable by name.
_latest_cache: dict = {}


def _latest_source_row(conn: sqlite3.Connection, source: str):
    cursor = conn.cursor()
    cursor.execute("PRAGMA database_list")
    db_file = cursor.fetchone()[2]

    cursor.execute("SELECT COUNT(*) FROM usage_history WHERE source=?", (source,))
    usage_count = cursor.fetchone()[0]
    if not usage_count:
        return None
    cursor.execute("SELECT COUNT(*) FROM model_usage WHERE source=?", (source,))
    model_count = cursor.fetchone()[0]
    cursor.execute(
        "SELECT * FROM usage_history WHERE source=? ORDER BY cycle_ts DESC LIMIT 1", (source,))
    fingerprint = (usage_count, model_count, tuple(cursor.fetchone()))

    cache_key = (db_file, source) if db_file else None
    if cache_key:
        hit = _latest_cache.get(cache_key)
        if hit and hit[0] == fingerprint:
            return hit[1]

    rows = _derived_source_history(conn, source, latest_only=True)
    row = rows[-1] if rows else None
    if cache_key:
        _latest_cache[cache_key] = (fingerprint, row)
    return row


def history(conn: sqlite3.Connection, source: str = None) -> list:
    if source is not None:
        return _derived_source_history(conn, source)

    # Aggregated view: derive each source, forward-fill cumulative totals
    # across the union of cycles (a source that skipped a cycle hasn't lost
    # usage, so its total carries forward rather than dipping to zero), then
    # sum. Deltas only count cycles where the source actually reported.
    from source_registry import get_all_names
    per_source = {}
    for src in get_all_names():
        rows = _derived_source_history(conn, src, with_models=False)
        if rows:
            per_source[src] = {r['cycle_ts']: r for r in rows}

    all_cycles = sorted({cts for rows in per_source.values() for cts in rows})
    out = []
    last_totals = {src: {f: 0 for f in _USAGE_FIELDS} for src in per_source}
    for cts in all_cycles:
        agg = {f: 0 for f in _USAGE_FIELDS}
        agg_delta = {f: 0 for f in _USAGE_FIELDS}
        for src, rows in per_source.items():
            row = rows.get(cts)
            if row:
                last_totals[src] = {f: row[f] for f in _USAGE_FIELDS}
                for f in _USAGE_FIELDS:
                    agg_delta[f] += row[f'delta_{f}']
            for f in _USAGE_FIELDS:
                agg[f] += last_totals[src][f]
        entry = {
            'cycle_ts': cts,
            'timestamp': datetime.fromtimestamp(cts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
        }
        entry.update(agg)
        entry.update({f'delta_{f}': agg_delta[f] for f in _USAGE_FIELDS})
        out.append(entry)
    return out


def latest_usage(conn: sqlite3.Connection, source: str = None, cycle_ts: int = None, include_model_deltas: bool = False) -> dict:
    if source is not None:
        sources = [source]
    else:
        from source_registry import get_all_names
        sources = get_all_names()

    result = {}
    for src in sources:
        if cycle_ts is None:
            row = _latest_source_row(conn, src)
        else:
            # Historical lookup: needs that cycle's derived row, so no
            # shortcut past the full materialization.
            rows = [r for r in _derived_source_history(conn, src)
                    if r['cycle_ts'] == cycle_ts]
            row = rows[-1] if rows else None
        if row is None:
            continue
        # Cached rows are shared across calls; hand out a copy so callers
        # (including the model_deltas augmentation below) never mutate them.
        row = dict(row)
        if include_model_deltas:
            # Per-model change during the latest cycle — already computed by
            # the derivation as delta_* on each model row.
            row['model_deltas'] = [
                {
                    'model_name': m['model_name'],
                    'messages': m['delta_messages'],
                    'input_tokens': m['delta_input_tokens'],
                    'output_tokens': m['delta_output_tokens'],
                    'cost': 0.0,
                }
                for m in row.get('models', [])
            ]
        result[src] = row
    return result


# --- Quota ---

def _do_insert_quota(conn, source, cycle_ts, data):
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

    if isinstance(data, dict):
        for key, val in data.items():
            if not isinstance(val, dict):
                continue
            for subkey, subval in val.items():
                if isinstance(subval, dict):
                    has_deep_nesting = any(isinstance(leaf, dict) for leaf in subval.values())
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
            _save_quota_row(conn, ts_str, source, cycle_ts,
                            r.get('model_group'), r.get('limit_type'), r)

    # Same invariant as _do_insert_usage: pair every quota write with a
    # collection_status row at the data layer, not by caller discipline.
    conn.execute('''
        INSERT OR REPLACE INTO collection_status (source, kind, cycle_ts, timestamp, ok, error, duration_ms)
        VALUES (?, 'quota', ?, ?, 1, NULL, 0.0)
    ''', (source, cycle_ts, ts_str))

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
    if source is not None:
        sources = [source]
    else:
        from source_registry import get_all_names
        sources = get_all_names()

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

    return result


# --- Maintenance ---

def metrics(conn: sqlite3.Connection) -> dict:
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT source FROM collection_status")
    sources = [r['source'] for r in cursor.fetchall()]

    per_source = {}
    for src in sources:
        cursor.execute(
            "SELECT kind, timestamp, ok, error, duration_ms FROM collection_status "
            "WHERE source=? ORDER BY id DESC LIMIT 2",
            (src,)
        )
        rows = cursor.fetchall()
        src_info = {}
        for row in rows:
            kind = row['kind']
            src_info[kind] = {
                'last_success_at': row['timestamp'] if row['ok'] else None,
                'last_error': None if row['ok'] else row['error'],
                'last_duration_ms': row['duration_ms'],
            }
        per_source[src] = src_info

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
    """Delete rows older than the retention window, but keep the newest
    pre-cutoff observation per source as an anchor: the first retained
    cycle's delta is still computed against a real prior reading instead of
    counting as a first observation (delta 0). Derived totals therefore mean
    "cumulative over the retention window"."""
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_ts = int(cutoff_time.timestamp())

    conn.execute('''
        DELETE FROM usage_history WHERE cycle_ts < :cut AND cycle_ts <> (
            SELECT MAX(cycle_ts) FROM usage_history AS h
            WHERE h.source = usage_history.source AND h.cycle_ts < :cut
        )
    ''', {'cut': cutoff_ts})
    conn.execute('''
        DELETE FROM model_usage WHERE cycle_ts < :cut AND cycle_ts <> (
            SELECT MAX(cycle_ts) FROM model_usage AS m
            WHERE m.source = model_usage.source AND m.cycle_ts < :cut
        )
    ''', {'cut': cutoff_ts})
    conn.execute("DELETE FROM quota_snapshots WHERE cycle_ts < ?", (cutoff_ts,))
    conn.execute("DELETE FROM collection_status WHERE cycle_ts < ?", (cutoff_ts,))

    conn.commit()
