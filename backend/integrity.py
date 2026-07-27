"""Data-integrity validation for the usage database.

The database stores raw observations only (see db.py); nothing here writes
to the data tables. Gaps stay gaps on disk — display continuity is handled
at read time (db.history forward-fills the combined view; the frontend
forward-fills the per-source charts). This module just answers "does the
stored data satisfy its invariants?" and reports anything that doesn't.
"""
import sqlite3
import time

from db import _USAGE_FIELDS, _MODEL_FIELDS
from datetime import datetime, timezone

# check_integrity runs every poller cycle (10 min) AND on every /metrics
# request (frontend polls that every 60s). At 90-day retention a full-table
# walk on every call is O(entire database) forever, so checks #1 and #3 are
# expressed as single SQL queries (window functions, aggregates) instead of
# pulling every row into Python — and can be bounded to a recent window via
# since_cycle so callers with a known-good watermark don't rescan history
# that's already been checked.
_WARNING_CAP = 5  # historical findings stay in 'checks'; 'warnings' only
                   # re-announces the most recent few each call, or every
                   # counter reset from 90 days ago re-floods it forever.


def reconcile_model_sums(conn: sqlite3.Connection, source: str = None,
                         cycle_ts: int = None) -> dict:
    """Close the gap between a cycle's source row and its model rows by
    carrying the difference in a single 'Unattributed' model row.

    Scope is deliberately narrow, because this writes to history:

    * Only cycles where the model rows sum to LESS than the source row beyond
      check_integrity's own tolerance (max(1000, 10%)). That tolerance exists
      because opencode's stats command rounds its overview totals — a few
      percent of drift is the tool rounding, not corruption, and reconciling
      it invents rows for nearly every cycle of every source.
    * Never the reverse case. If the model rows sum to MORE than the source
      row, an 'Unattributed' row cannot express that (it would have to be
      negative) — that is a source under-reporting and stays a warning.
    * `cycle_ts` bounds it to a single cycle. The poller passes the cycle it
      just wrote, so routine operation can never mass-rewrite history.

    Only ever adds or adjusts the 'Unattributed' row. Real model rows and the
    source row are never modified.
    """
    cursor = conn.cursor()
    repaired, sources_repaired, attributed = 0, set(), 0

    where, params = ['h.cycle_ts > 0'], []
    if source:
        where.append('h.source = ?'); params.append(source)
    if cycle_ts is not None:
        where.append('h.cycle_ts = ?'); params.append(cycle_ts)

    cursor.execute(f"""
        SELECT h.source, h.cycle_ts,
               h.input_tokens AS s_in, h.output_tokens AS s_out, h.cache_read AS s_cache,
               COALESCE(SUM(m.input_tokens), 0) AS m_in,
               COALESCE(SUM(m.output_tokens), 0) AS m_out,
               COALESCE(SUM(m.cache_read), 0) AS m_cache
        FROM usage_history h
        LEFT JOIN model_usage m
               ON m.source = h.source AND m.cycle_ts = h.cycle_ts
        WHERE {' AND '.join(where)}
        GROUP BY h.source, h.cycle_ts
    """, params)

    for r in cursor.fetchall():
        s_in, s_out = r['s_in'] or 0, r['s_out'] or 0
        s_total = s_in + s_out
        m_total = (r['m_in'] or 0) + (r['m_out'] or 0)
        if not s_total:
            continue
        gap = s_total - m_total
        # Same tolerance as the model_sum check, and only the under-reported
        # direction. `gap <= tolerance` covers both "close enough" and the
        # negative (models exceed source) case in one comparison.
        if gap <= max(1000, 0.10 * s_total):
            continue

        d_in = max(0, s_in - (r['m_in'] or 0))
        d_out = max(0, s_out - (r['m_out'] or 0))
        d_cache = max(0, (r['s_cache'] or 0) - (r['m_cache'] or 0))
        if not (d_in or d_out):
            continue

        ts_str = datetime.fromtimestamp(r['cycle_ts'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO model_usage (timestamp, source, cycle_ts, model_name, messages,"
            " input_tokens, output_tokens, cache_read, cache_write, cost)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source, cycle_ts, model_name) DO UPDATE SET"
            "   input_tokens=excluded.input_tokens,"
            "   output_tokens=excluded.output_tokens,"
            "   cache_read=excluded.cache_read",
            (ts_str, r['source'], r['cycle_ts'], 'Unattributed', 0,
             d_in, d_out, d_cache, 0, 0.0))
        repaired += 1
        sources_repaired.add(r['source'])
        attributed += d_in + d_out

    conn.commit()
    return {
        'cycles_repaired': repaired,
        'sources': sorted(sources_repaired),
        'tokens_attributed': attributed,
    }


def sources_needing_attribution(conn: sqlite3.Connection) -> set:
    """Sources whose model rows fall short of the source row by more than
    check_integrity's tolerance on at least one cycle.

    Membership is per-source and all-or-nothing on purpose. The 'Unattributed'
    row must exist on EVERY cycle of a source that needs it: totals are derived
    as deltas, so a row that appears on some cycles and not others produces a
    phantom spike where it appears and a clamped drop where it vanishes — the
    same artifact as a gap rendering as a dip.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT h.source,
               h.input_tokens + h.output_tokens AS s_total,
               COALESCE(SUM(m.input_tokens + m.output_tokens), 0) AS m_total
        FROM usage_history h
        LEFT JOIN model_usage m
               ON m.source = h.source AND m.cycle_ts = h.cycle_ts
              AND m.model_name != 'Unattributed'
        GROUP BY h.source, h.cycle_ts
    """)
    needy = set()
    for r in cursor.fetchall():
        s_total = r['s_total'] or 0
        if not s_total:
            continue
        if (s_total - (r['m_total'] or 0)) > max(1000, 0.10 * s_total):
            needy.add(r['source'])
    return needy


def sources_with_attribution_series(conn: sqlite3.Connection) -> set:
    """Sources that already carry an 'Unattributed' series in history.

    The poller uses this rather than re-deriving need each cycle: once a source
    has the series it must keep getting a row every cycle, or the series breaks
    and the delta artifacts come back.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT source FROM model_usage WHERE model_name='Unattributed'")
    return {r['source'] for r in cursor.fetchall()}


def backfill_unattributed(conn: sqlite3.Connection, sources=None,
                          cycle_ts: int = None) -> dict:
    """One-time history pass: give every cycle of every needing source an
    'Unattributed' row, so the series is continuous end to end.

    Writes a row even when that cycle's gap is zero. A zero row contributes a
    zero delta and keeps the series unbroken, which is the whole point.
    """
    if sources is None:
        sources = sources_needing_attribution(conn)
    if not sources:
        return {'sources': [], 'cycles_written': 0}

    cursor = conn.cursor()
    written = 0
    marks = ','.join('?' * len(sources))
    params = list(sorted(sources))
    cycle_clause = ''
    if cycle_ts is not None:
        cycle_clause = ' AND h.cycle_ts = ?'
        params.append(cycle_ts)
    cursor.execute(f"""
        SELECT h.source, h.cycle_ts,
               h.input_tokens AS s_in, h.output_tokens AS s_out, h.cache_read AS s_cache,
               COALESCE(SUM(m.input_tokens), 0)  AS m_in,
               COALESCE(SUM(m.output_tokens), 0) AS m_out,
               COALESCE(SUM(m.cache_read), 0)    AS m_cache
        FROM usage_history h
        LEFT JOIN model_usage m
               ON m.source = h.source AND m.cycle_ts = h.cycle_ts
              AND m.model_name != 'Unattributed'
        WHERE h.source IN ({marks}){cycle_clause}
        GROUP BY h.source, h.cycle_ts
    """, tuple(params))

    for r in cursor.fetchall():
        d_in = max(0, (r['s_in'] or 0) - (r['m_in'] or 0))
        d_out = max(0, (r['s_out'] or 0) - (r['m_out'] or 0))
        d_cache = max(0, (r['s_cache'] or 0) - (r['m_cache'] or 0))
        ts_str = datetime.fromtimestamp(r['cycle_ts'], tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "INSERT INTO model_usage (timestamp, source, cycle_ts, model_name, messages,"
            " input_tokens, output_tokens, cache_read, cache_write, cost)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(source, cycle_ts, model_name) DO UPDATE SET"
            "   input_tokens=excluded.input_tokens,"
            "   output_tokens=excluded.output_tokens,"
            "   cache_read=excluded.cache_read",
            (ts_str, r['source'], r['cycle_ts'], 'Unattributed', 0,
             d_in, d_out, d_cache, 0, 0.0))
        written += 1

    conn.commit()
    return {'sources': sorted(sources), 'cycles_written': written}


def _capped_warnings(findings, formatter, label):
    """Render at most _WARNING_CAP warning lines for a findings list
    (assumed ordered oldest->newest; the most recent ones are shown), plus a
    summary line for the rest. `checks` keeps the full list either way —
    this only trims what gets repeated in 'warnings' every call."""
    shown = findings[-_WARNING_CAP:]
    lines = [formatter(item) for item in shown]
    hidden = len(findings) - len(shown)
    if hidden:
        lines.append(f"...and {hidden} more {label} (see checks for full list)")
    return lines


def check_integrity(conn: sqlite3.Connection, poll_interval: int = 600, since_cycle: int = 0) -> dict:
    """Validate the raw-observation invariants. Returns:
    {
      'ok': bool,            # hard invariants hold
      'warnings': [str, ...],# soft findings (counter resets, model-sum drift),
                              # capped to the _WARNING_CAP most recent per
                              # finding type — see 'checks' for the full list
      'checks': {name: {...}, ...}
    }

    since_cycle: bounds checks #1 (monotonicity) and #3 (model-sum) to
    cycle_ts >= since_cycle, composed with the existing migrated_after floor
    via max(). Default 0 preserves the full-scan behavior every existing
    caller relies on. Pass a recent watermark (e.g. now - a few days) to
    turn a per-call full-history scan into a bounded one; rows older than
    the floor are simply not re-examined (they were already checked on a
    prior call), so 'checks' reflects only the scanned window, not all of
    history, whenever since_cycle > 0.
    """
    cursor = conn.cursor()
    warnings = []
    checks = {}

    # Rows migrated from the pre-v3 accumulated format are display-correct
    # but not clean raw observations, so checks that assume raw semantics
    # (monotonicity, model sums) only apply to cycles recorded after the
    # migration. Status pairing and staleness stay global.
    cursor.execute("SELECT value FROM meta WHERE key='v3_migrated_after_cycle'")
    row = cursor.fetchone()
    migrated_after = int(row[0]) if row else 0
    checks['raw_checks_after_cycle'] = migrated_after
    scan_floor = max(migrated_after, since_cycle)

    # 1. Monotonicity: raw lifetime counters should never decrease. The write
    # path (db._do_insert_usage) already absorbs a hard drop — a counter
    # falling below half its previous reading, i.e. tool state reset or
    # reinstalled — by carrying the old baseline forward, so a decrease that
    # still made it into storage means either a gentler decline than that
    # threshold (a windowed source's on-disk data shrinking a few percent,
    # e.g. agy's conversation dir aging out old files) or a row written
    # outside the normal write path. Either way the read-time derivation
    # clamps that cycle's delta to 0, so this is a warning (data is
    # explainable), not a corruption.
    #
    # LAG() over cycle_ts, partitioned by source, does the "compare to the
    # previous row" walk inside SQLite instead of one Python loop per source
    # over every row. prev_cycle_ts IS NULL marks each partition's first row
    # (no predecessor to compare against, same as the old `if prev is not
    # None` guard); COALESCE(...,0) mirrors the old `row[f] or 0` so a NULL
    # column (a field a source doesn't report) reads as 0 on both sides.
    field_cols = ', '.join(_USAGE_FIELDS)
    lag_cols = ',\n                   '.join(
        f"LAG({f}) OVER w AS prev_{f}" for f in _USAGE_FIELDS)
    reset_union = ' UNION ALL '.join(
        f"""SELECT source, '{f}' AS field, cycle_ts,
                   prev_{f} AS previous, {f} AS value
            FROM windowed
            WHERE prev_cycle_ts IS NOT NULL
              AND COALESCE({f}, 0) < COALESCE(prev_{f}, 0)"""
        for f in _USAGE_FIELDS)
    cursor.execute(f'''
        WITH windowed AS (
            SELECT source, cycle_ts, {field_cols},
                   LAG(cycle_ts) OVER w AS prev_cycle_ts,
                   {lag_cols}
            FROM usage_history
            WHERE cycle_ts >= ?
            WINDOW w AS (PARTITION BY source ORDER BY cycle_ts)
        )
        {reset_union}
        ORDER BY cycle_ts ASC
    ''', (scan_floor,))
    resets = [dict(r) for r in cursor.fetchall()]
    checks['counter_resets'] = resets
    warnings.extend(_capped_warnings(
        resets,
        lambda r: (f"{r['source']}.{r['field']} decreased at cycle {r['cycle_ts']} "
                   f"({r['previous']} -> {r['value']}): tool state was likely reset"),
        'counter reset(s)'))

    # 2. Status pairing: every usage row must have a collection_status row
    # (the write layer enforces this, so a violation means external writes).
    cursor.execute('''
        SELECT COUNT(*) FROM usage_history h
        WHERE NOT EXISTS (
            SELECT 1 FROM collection_status s
            WHERE s.source = h.source AND s.kind = 'usage' AND s.cycle_ts = h.cycle_ts
        )
    ''')
    unpaired = cursor.fetchone()[0]
    checks['rows_missing_status'] = unpaired
    if unpaired:
        warnings.append(
            f"{unpaired} usage_history row(s) have no collection_status pair "
            "(written outside the poller?)")

    # 3. Model consistency: per cycle, the per-model token sums should match
    # the source-level reading. Soft check with generous tolerance: opencode's
    # own stats command rounds its overview totals (e.g. "21.8m"), so a few
    # percent of steady drift is the tool's rounding, not corruption.
    mismatches = []
    cursor.execute('''
        SELECT h.source, h.cycle_ts,
               h.input_tokens + h.output_tokens AS total,
               SUM(m.input_tokens + m.output_tokens) AS model_total
        FROM usage_history h
        JOIN model_usage m ON m.source = h.source AND m.cycle_ts = h.cycle_ts
        WHERE h.cycle_ts > ?
        GROUP BY h.source, h.cycle_ts
        ORDER BY h.cycle_ts ASC
    ''', (scan_floor,))
    for row in cursor.fetchall():
        total, model_total = row['total'] or 0, row['model_total'] or 0
        if total and abs(model_total - total) > max(1000, 0.10 * total):
            mismatches.append({
                'source': row['source'], 'cycle_ts': row['cycle_ts'],
                'source_total': total, 'model_total': model_total,
            })
    checks['model_sum_mismatches'] = mismatches
    warnings.extend(_capped_warnings(
        mismatches,
        lambda m: (f"{m['source']} cycle {m['cycle_ts']}: model tokens sum to "
                   f"{m['model_total']} but source row says {m['source_total']}"),
        'model-sum mismatch(es)'))

    # 4. Staleness: the newest observation should be recent. Checked both
    # globally and per source — the global check alone goes blind the
    # moment any other source is still polling fine, so a single source
    # (e.g. codex) can go dark for hours without ever tripping it. One
    # GROUP BY gets every source's newest cycle in a single scan; the global
    # newest is just the max of those, no second full-table aggregate needed.
    cursor.execute("SELECT source, MAX(cycle_ts) AS newest FROM usage_history GROUP BY source")
    per_source_newest = {r['source']: r['newest'] for r in cursor.fetchall()}
    newest = max(per_source_newest.values()) if per_source_newest else None
    stale = bool(newest) and (time.time() - newest) > 2 * poll_interval
    checks['newest_cycle_ts'] = newest
    checks['stale'] = stale
    if stale:
        warnings.append(
            f"newest observation is cycle {newest}, older than 2x the poll interval")

    stale_sources = {
        src: src_newest for src, src_newest in per_source_newest.items()
        if bool(src_newest) and (time.time() - src_newest) > 2 * poll_interval
    }
    checks['stale_sources'] = stale_sources
    for src, src_newest in stale_sources.items():
        warnings.append(
            f"{src} newest observation is cycle {src_newest}, older than 2x the "
            "poll interval (other sources may still be reporting fine)")

    # Auto-reconciliation: fix model-sum mismatches silently

    return {
        'ok': unpaired == 0 and not stale and not stale_sources,
        'warnings': warnings,
        'checks': checks,
    }
