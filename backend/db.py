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

One amendment to "exactly as reported": the counters these parsers read are
files on disk, and wiping/archiving those files (e.g. codex sessions moved
to ~/.codex/archived_sessions) collapses the tool's own numbers even though
no usage un-happened. The write path treats a hard drop (a counter falling
below half its previous reading) as such a state loss and carries the old
baseline forward via a per-source offset persisted in meta, so the stored
series stays cumulative across tool resets. Gentle declines (agy's
conversation dir shrinking a few percent as old files age out) are below
the threshold and still stored verbatim — the read-time clamp handles them.
"""
import json
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


def rebase_reset_history(conn: sqlite3.Connection, source: str) -> dict:
    """One-time repair: replay one source's stored history through the same
    reset-rebase rule _do_insert_usage now applies at write time, rewriting
    rows in place and leaving the accumulated offsets in meta so the next
    live write continues the rebased series seamlessly.

    Only rows after the v3 migration floor are touched (earlier rows are
    migrated display data, not raw readings). Run with the poller stopped —
    a raw write landing mid-replay would be skipped by it.

    Ghost promotion is deferred by one cycle: a poller restart can leave a
    reset cycle holding the union of pre- and post-reset model rows (same
    bucket written twice via INSERT OR REPLACE), so "missing at the reset
    cycle itself" is unreliable; a model is frozen when it is still absent
    at the first cycle after the reset."""
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM meta WHERE key='v3_migrated_after_cycle'")
    row = cursor.fetchone()
    floor = int(row[0]) if row else 0

    offsets = _load_reset_offsets(conn, source)
    src_off, model_off = offsets['source'], offsets['models']

    cursor.execute(
        'SELECT * FROM usage_history WHERE source=? AND cycle_ts>=? ORDER BY cycle_ts ASC',
        (source, floor))
    rows = cursor.fetchall()
    cursor.execute(
        'SELECT * FROM model_usage WHERE source=? AND cycle_ts>=? ORDER BY cycle_ts ASC',
        (source, floor))
    models_by_cycle: dict = {}
    for r in cursor.fetchall():
        models_by_cycle.setdefault(r['cycle_ts'], {})[r['model_name']] = r

    summary = {'source_resets': 0, 'rows_rebased': 0, 'model_rows_rebased': 0,
               'ghost_rows_added': 0, 'ghost_models': []}
    # Unlike _do_insert_usage (which re-reads the previous row from the DB on
    # every call, so it always sees a value some earlier call already baked
    # an offset into), this walks one static snapshot fetched up front: none
    # of these historical rows have ever had an offset applied. So resets are
    # detected by comparing literal stored readings to each other (exactly
    # like integrity.py's monotonicity check does), and the running offset
    # is only ever added when writing a row back — never subtracted back out
    # of a reading to "recover" a raw value that was never adjusted to begin
    # with.
    prev_stored = None
    last_model_stored: dict = {}
    pending_ghosts: dict = {}
    for idx, r in enumerate(rows):
        cycle = r['cycle_ts']
        stored = {f: (r[f] or 0) for f in _USAGE_FIELDS}
        cur_models = models_by_cycle.get(cycle, {})

        for name, ghost in list(pending_ghosts.items()):
            if name not in cur_models:
                model_off[name] = ghost
                summary['ghost_models'].append(name)
            del pending_ghosts[name]

        source_reset = False
        if prev_stored is not None:
            for f in _USAGE_FIELDS:
                if _is_reset(stored[f], prev_stored[f]):
                    src_off[f] = src_off.get(f, 0) + prev_stored[f]
                    source_reset = True
        if source_reset:
            summary['source_resets'] += 1
            prev_cycle_models = models_by_cycle.get(
                rows[idx - 1]['cycle_ts'], {}) if idx else {}
            for name, prev_row in prev_cycle_models.items():
                # Freeze at the last *stored* value (offset already baked
                # in), not the raw reading — a model that already carried
                # its own offset from an earlier reset must keep it.
                pending_ghosts[name] = {f: (prev_row[f] or 0) for f in _MODEL_REBASE_FIELDS}
        if any(src_off.get(f, 0) for f in _USAGE_FIELDS):
            sets = ', '.join(f'{f}=?' for f in _USAGE_FIELDS)
            conn.execute(
                f'UPDATE usage_history SET {sets} WHERE id=?',
                tuple(stored[f] + src_off.get(f, 0) for f in _USAGE_FIELDS) + (r['id'],))
            summary['rows_rebased'] += 1

        for name, mr in cur_models.items():
            off = model_off.get(name, {})
            m_stored = {f: (mr[f] or 0) for f in _MODEL_REBASE_FIELDS}
            prev_m = last_model_stored.get(name)
            if prev_m is not None:
                for f in _MODEL_REBASE_FIELDS:
                    if source_reset and _is_reset(m_stored[f], prev_m[f]):
                        off[f] = off.get(f, 0) + prev_m[f]
                        model_off[name] = off
            if any(off.get(f, 0) for f in _MODEL_REBASE_FIELDS):
                sets = ', '.join(f'{f}=?' for f in _MODEL_REBASE_FIELDS)
                conn.execute(
                    f'UPDATE model_usage SET {sets} WHERE id=?',
                    tuple(m_stored[f] + off.get(f, 0) for f in _MODEL_REBASE_FIELDS) + (mr['id'],))
                summary['model_rows_rebased'] += 1
            last_model_stored[name] = m_stored

        for name, off in model_off.items():
            if name in cur_models:
                continue
            conn.execute('''
                INSERT OR IGNORE INTO model_usage (
                    timestamp, source, cycle_ts, model_name, messages,
                    input_tokens, output_tokens, cache_read, cache_write, cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (r['timestamp'], source, cycle, name) + tuple(
                off.get(f, 0) for f in _MODEL_REBASE_FIELDS))
            summary['ghost_rows_added'] += 1
            # A ghost cycle contributes zero raw usage for this model (same
            # as a live ghost row _do_insert_usage would read back), so a
            # model that later reappears is compared against 0, not its
            # stale pre-ghost reading — otherwise a genuine resumed count
            # would misfire as another reset.
            last_model_stored[name] = {f: 0 for f in _MODEL_REBASE_FIELDS}

        prev_stored = stored

    if src_off or model_off:
        _save_reset_offsets(conn, source, offsets)
    conn.commit()
    return summary


def init_db():
    conn = connect(DB_PATH)
    init_schema(conn)
    conn.close()


# --- Writers (the poller is the only intended caller) ---

def record_observation(conn: sqlite3.Connection, source: str, cycle_ts: int, result) -> None:
    """Store a parser's reading. `result` is a ParserResult (or anything
    with the same attributes). Readings are stored verbatim except across a
    tool-state reset (see the module docstring), where the pre-reset
    baseline is carried forward so the stored series stays cumulative."""
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


# A counter falling below this fraction of its previous reading is treated
# as tool state loss (reinstall, sessions archived/deleted) rather than the
# normal jitter of a windowed source, whose on-disk data shrinks by a few
# percent as old files age out.
_RESET_DROP_RATIO = 0.5

_MODEL_REBASE_FIELDS = _MODEL_FIELDS + ('cost',)


def _is_reset(raw, last_raw) -> bool:
    return last_raw > 0 and raw < last_raw * _RESET_DROP_RATIO


def _load_reset_offsets(conn, source: str) -> dict:
    """Per-source rebase state persisted in meta: {'source': {field: offset},
    'models': {model_name: {field: offset}}}. An offset is the cumulative
    count a tool had reached before wiping its own state; stored values are
    the tool's current reading plus the offset. A model entry whose model no
    longer appears in the parse doubles as a frozen ('ghost') row — see
    _do_insert_usage."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key=?", (f'reset_offsets:{source}',)).fetchone()
    data = json.loads(row['value']) if row else {}
    data.setdefault('source', {})
    data.setdefault('models', {})
    return data


def _save_reset_offsets(conn, source: str, offsets: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (f'reset_offsets:{source}', json.dumps(offsets)))


def _do_insert_usage(conn, source, cycle_ts, sessions, messages, input_tokens, output_tokens, cache_read, cache_write, models):
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    raw = dict(zip(_USAGE_FIELDS, (
        sessions or 0, messages or 0, input_tokens or 0,
        output_tokens or 0, cache_read or 0, cache_write or 0)))

    # Reset rebase: compare against the last *earlier* cycle (a same-cycle
    # INSERT OR REPLACE rewrite must not compare a reading against itself).
    # last stored - offset recovers the tool's own previous reading.
    offsets = _load_reset_offsets(conn, source)
    src_off = offsets['source']
    prev = conn.execute(
        'SELECT * FROM usage_history WHERE source=? AND cycle_ts<? '
        'ORDER BY cycle_ts DESC LIMIT 1', (source, cycle_ts)).fetchone()
    source_reset = False
    if prev is not None:
        for f in _USAGE_FIELDS:
            last_raw = (prev[f] or 0) - src_off.get(f, 0)
            if _is_reset(raw[f], last_raw):
                src_off[f] = src_off.get(f, 0) + last_raw
                source_reset = True

    conn.execute('''
        INSERT OR REPLACE INTO usage_history (
            timestamp, source, cycle_ts, sessions, messages,
            input_tokens, output_tokens, cache_read, cache_write
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (ts_str, source, cycle_ts) + tuple(
        raw[f] + src_off.get(f, 0) for f in _USAGE_FIELDS))

    parsed = {}
    for m in models or []:
        md = _model_to_dict(m)
        if md is not None:
            parsed[md['model_name']] = md

    model_off = offsets['models']
    if source_reset and prev is not None:
        # Models the tool reported last cycle but no longer knows about were
        # wiped with the rest of its state; freeze each at its last stored
        # value so per-cycle model sums keep matching the rebased source row.
        for r in conn.execute(
                'SELECT * FROM model_usage WHERE source=? AND cycle_ts=?',
                (source, prev['cycle_ts'])):
            if r['model_name'] not in parsed:
                model_off[r['model_name']] = {
                    f: (r[f] or 0) for f in _MODEL_REBASE_FIELDS}

    for name, md in parsed.items():
        off = model_off.get(name, {})
        prev_m = conn.execute(
            'SELECT * FROM model_usage WHERE source=? AND model_name=? AND cycle_ts<? '
            'ORDER BY cycle_ts DESC LIMIT 1', (source, name, cycle_ts)).fetchone()
        if prev_m is not None:
            for f in _MODEL_REBASE_FIELDS:
                if source_reset:
                    last_raw = (prev_m[f] or 0) - off.get(f, 0)
                    if _is_reset(md[f] or 0, last_raw):
                        off[f] = off.get(f, 0) + last_raw
                        model_off[name] = off
        conn.execute('''
            INSERT OR REPLACE INTO model_usage (
                timestamp, source, cycle_ts, model_name, messages,
                input_tokens, output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts_str, source, cycle_ts, name) + tuple(
            (md[f] or 0) + off.get(f, 0) for f in _MODEL_REBASE_FIELDS))

    # Ghost rows: a model frozen at a reset keeps one row per cycle so it
    # stays in the per-model breakdown and in the model-sum invariant.
    for name, off in model_off.items():
        if name in parsed:
            continue
        conn.execute('''
            INSERT OR REPLACE INTO model_usage (
                timestamp, source, cycle_ts, model_name, messages,
                input_tokens, output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ts_str, source, cycle_ts, name) + tuple(
            off.get(f, 0) for f in _MODEL_REBASE_FIELDS))

    if src_off or model_off:
        _save_reset_offsets(conn, source, offsets)

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

    # "Newest two rows for this source" (the old approach) silently assumed
    # those two rows are one 'usage' and one 'quota' row. Two consecutive
    # same-kind rows make the other kind vanish from the report, so group by
    # (source, kind) instead. Two grouped-aggregate queries plus one row
    # fetch by id keeps this index-friendly rather than a full-table walk.
    cursor.execute("SELECT source, kind, MAX(id) AS newest_id FROM collection_status GROUP BY source, kind")
    newest_id_by_key = {(r['source'], r['kind']): r['newest_id'] for r in cursor.fetchall()}

    # Newest *successful* attempt per (source, kind), tracked separately from
    # the newest attempt overall: after a run of failures, last_success_at
    # must still be the time of the last real success, not None.
    cursor.execute(
        "SELECT source, kind, MAX(id) AS success_id FROM collection_status WHERE ok=1 GROUP BY source, kind")
    success_id_by_key = {(r['source'], r['kind']): r['success_id'] for r in cursor.fetchall()}

    wanted_ids = set(newest_id_by_key.values()) | set(success_id_by_key.values())
    rows_by_id = {}
    if wanted_ids:
        placeholders = ','.join('?' * len(wanted_ids))
        cursor.execute(
            f"SELECT id, timestamp, ok, error, duration_ms FROM collection_status WHERE id IN ({placeholders})",
            tuple(wanted_ids)
        )
        rows_by_id = {r['id']: r for r in cursor.fetchall()}

    per_source = {}
    for (src, kind), newest_id in newest_id_by_key.items():
        newest_row = rows_by_id[newest_id]
        success_id = success_id_by_key.get((src, kind))
        per_source.setdefault(src, {})[kind] = {
            'last_success_at': rows_by_id[success_id]['timestamp'] if success_id else None,
            'last_error': None if newest_row['ok'] else newest_row['error'],
            'last_duration_ms': newest_row['duration_ms'],
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
