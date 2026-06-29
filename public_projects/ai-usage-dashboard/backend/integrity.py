import sqlite3
from datetime import datetime, timezone

def fix_cycle_integrity(conn: sqlite3.Connection, cycle_ts: int) -> None:
    """Ensures that all expected sources ('opencode', 'agy', 'codex') have rows for cycle_ts.
    
    If any expected source is missing a row in usage_history, we find the latest preceding
    row for that source and carry its values forward.
    """
    cursor = conn.cursor()
    
    # 1. Determine which sources are already recorded for this cycle_ts
    cursor.execute("SELECT DISTINCT source FROM usage_history WHERE cycle_ts=?", (cycle_ts,))
    existing_sources = {row[0] for row in cursor.fetchall()}
    
    # If no source has recorded data for this cycle, then the cycle was pruned or not polled
    if not existing_sources:
        cursor.execute("SELECT COUNT(*) FROM collection_status WHERE cycle_ts=?", (cycle_ts,))
        if cursor.fetchone()[0] == 0:
            return
        
    expected_sources = {'opencode', 'agy', 'codex'}
    missing_sources = expected_sources - existing_sources
    
    if not missing_sources:
        return
        
    # Formatting helper for the timestamp string
    ts_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    
    for src in missing_sources:
        # Find the latest preceding record for this source
        cursor.execute('''
            SELECT * FROM usage_history
            WHERE source=? AND cycle_ts < ? AND cycle_ts > 0
            ORDER BY cycle_ts DESC LIMIT 1
        ''', (src, cycle_ts))
        prev_row = cursor.fetchone()
        
        if prev_row:
            prev_data = dict(prev_row)
            prev_cycle_ts = prev_data.get('cycle_ts')
            
            # Prepare data to carry forward
            prev_data.pop('id', None)
            prev_data['cycle_ts'] = cycle_ts
            prev_data['timestamp'] = ts_str
            
            cols = prev_data.keys()
            placeholders = ', '.join(['?'] * len(cols))
            sql = f"INSERT OR REPLACE INTO usage_history ({', '.join(cols)}) VALUES ({placeholders})"
            conn.execute(sql, list(prev_data.values()))
            
            # Carry forward model usage
            cursor.execute('''
                SELECT * FROM model_usage
                WHERE source=? AND cycle_ts=?
            ''', (src, prev_cycle_ts))
            model_rows = [dict(r) for r in cursor.fetchall()]
            for mr_data in model_rows:
                mr_data.pop('id', None)
                mr_data['cycle_ts'] = cycle_ts
                mr_data['timestamp'] = ts_str
                
                m_cols = mr_data.keys()
                m_placeholders = ', '.join(['?'] * len(m_cols))
                m_sql = f"INSERT OR REPLACE INTO model_usage ({', '.join(m_cols)}) VALUES ({m_placeholders})"
                conn.execute(m_sql, list(mr_data.values()))
                
            # Carry forward quota snapshots
            cursor.execute('''
                SELECT * FROM quota_snapshots
                WHERE source=? AND cycle_ts=?
            ''', (src, prev_cycle_ts))
            quota_rows = [dict(r) for r in cursor.fetchall()]
            for qr_data in quota_rows:
                qr_data.pop('id', None)
                qr_data['cycle_ts'] = cycle_ts
                qr_data['timestamp'] = ts_str
                
                q_cols = qr_data.keys()
                q_placeholders = ', '.join(['?'] * len(q_cols))
                q_sql = f"INSERT OR REPLACE INTO quota_snapshots ({', '.join(q_cols)}) VALUES ({q_placeholders})"
                conn.execute(q_sql, list(qr_data.values()))


def fix_all_integrity(conn: sqlite3.Connection) -> None:
    """Finds all unique cycle_ts values in the database and runs fix_cycle_integrity on them."""
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT cycle_ts FROM collection_status WHERE cycle_ts > 0 ORDER BY cycle_ts ASC")
    cycles = [row[0] for row in cursor.fetchall()]
    
    for cycle_ts in cycles:
        fix_cycle_integrity(conn, cycle_ts)
    
    conn.commit()
