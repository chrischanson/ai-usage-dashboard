"""Data-integrity validation for the usage database.

The database stores raw observations only (see db.py); nothing here writes
to the data tables. Gaps stay gaps on disk — display continuity is handled
at read time (db.history forward-fills the combined view; the frontend
forward-fills the per-source charts). This module just answers "does the
stored data satisfy its invariants?" and reports anything that doesn't.
"""
import sqlite3
import time

from db import _USAGE_FIELDS


def check_integrity(conn: sqlite3.Connection, poll_interval: int = 600) -> dict:
    """Validate the raw-observation invariants. Returns:
    {
      'ok': bool,            # hard invariants hold
      'warnings': [str, ...],# soft findings (counter resets, model-sum drift)
      'checks': {name: {...}, ...}
    }
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

    # 1. Monotonicity: raw lifetime counters should never decrease. A
    # decrease means the tool's local state was reset/reinstalled — the
    # read-time derivation clamps that cycle's delta to 0, so this is a
    # warning (data is explainable), not a corruption.
    resets = []
    cursor.execute("SELECT DISTINCT source FROM usage_history")
    for (src,) in [tuple(r) for r in cursor.fetchall()]:
        cursor.execute(
            "SELECT * FROM usage_history WHERE source=? AND cycle_ts >= ? ORDER BY cycle_ts ASC",
            (src, migrated_after))
        prev = None
        for row in cursor.fetchall():
            if prev is not None:
                for f in _USAGE_FIELDS:
                    if (row[f] or 0) < (prev[f] or 0):
                        resets.append({
                            'source': src, 'field': f, 'cycle_ts': row['cycle_ts'],
                            'previous': prev[f], 'value': row[f],
                        })
            prev = row
    checks['counter_resets'] = resets
    for r in resets:
        warnings.append(
            f"{r['source']}.{r['field']} decreased at cycle {r['cycle_ts']} "
            f"({r['previous']} -> {r['value']}): tool state was likely reset")

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
    ''', (migrated_after,))
    for row in cursor.fetchall():
        total, model_total = row['total'] or 0, row['model_total'] or 0
        if total and abs(model_total - total) > max(1000, 0.10 * total):
            mismatches.append({
                'source': row['source'], 'cycle_ts': row['cycle_ts'],
                'source_total': total, 'model_total': model_total,
            })
    checks['model_sum_mismatches'] = mismatches
    for m in mismatches:
        warnings.append(
            f"{m['source']} cycle {m['cycle_ts']}: model tokens sum to "
            f"{m['model_total']} but source row says {m['source_total']}")

    # 4. Staleness: the newest observation should be recent. Checked both
    # globally and per source — the global check alone goes blind the
    # moment any other source is still polling fine, so a single source
    # (e.g. codex) can go dark for hours without ever tripping it.
    cursor.execute("SELECT MAX(cycle_ts) FROM usage_history")
    newest = cursor.fetchone()[0]
    stale = bool(newest) and (time.time() - newest) > 2 * poll_interval
    checks['newest_cycle_ts'] = newest
    checks['stale'] = stale
    if stale:
        warnings.append(
            f"newest observation is cycle {newest}, older than 2x the poll interval")

    stale_sources = {}
    cursor.execute("SELECT DISTINCT source FROM usage_history")
    for (src,) in [tuple(r) for r in cursor.fetchall()]:
        cursor.execute("SELECT MAX(cycle_ts) FROM usage_history WHERE source=?", (src,))
        src_newest = cursor.fetchone()[0]
        if bool(src_newest) and (time.time() - src_newest) > 2 * poll_interval:
            stale_sources[src] = src_newest
    checks['stale_sources'] = stale_sources
    for src, src_newest in stale_sources.items():
        warnings.append(
            f"{src} newest observation is cycle {src_newest}, older than 2x the "
            "poll interval (other sources may still be reporting fine)")

    return {
        'ok': unpaired == 0 and not stale and not stale_sources,
        'warnings': warnings,
        'checks': checks,
    }
