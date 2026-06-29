#!/usr/bin/env python3
"""Migration script for AI Usage Dashboard database schema version 2.

Reads the old data, computes cycle_ts, creates the new tables/indexes,
and inserts the migrated data with aligned timestamps.
"""
import os
import shutil
import sqlite3
from datetime import datetime, timezone

# Ensure correct path
DB_PATH = os.getenv('USAGE_DB_PATH') or os.path.join(os.path.dirname(__file__), "usage.db")
BACKUP_PATH = DB_PATH + ".bak"


def to_cycle_ts_and_str(ts_str):
    if not ts_str:
        return 0, ts_str
    try:
        dt = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        epoch = int(dt.timestamp())
        cycle_ts = (epoch // 600) * 600
        aligned_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        return cycle_ts, aligned_str
    except Exception:
        try:
            # Try ISO format
            dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            epoch = int(dt.timestamp())
            cycle_ts = (epoch // 600) * 600
            aligned_str = datetime.fromtimestamp(cycle_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            return cycle_ts, aligned_str
        except Exception:
            return 0, ts_str


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"No database found at {DB_PATH}. Nothing to migrate.")
        return

    print(f"Creating backup of {DB_PATH} to {BACKUP_PATH}...")
    shutil.copy2(DB_PATH, BACKUP_PATH)

    # Connect to old database to read data
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("Reading old records...")
    
    # 1. Read usage_history
    cursor.execute("SELECT * FROM usage_history")
    old_history = [dict(r) for r in cursor.fetchall()]
    
    # 2. Read model_usage
    cursor.execute("SELECT * FROM model_usage")
    old_model_usage = [dict(r) for r in cursor.fetchall()]
    
    # 3. Read quota_snapshots
    cursor.execute("SELECT * FROM quota_snapshots")
    old_quota = [dict(r) for r in cursor.fetchall()]
    
    # 4. Read collection_status
    cursor.execute("SELECT * FROM collection_status")
    old_status = [dict(r) for r in cursor.fetchall()]
    
    # 5. Read meta
    cursor.execute("SELECT * FROM meta")
    old_meta = [dict(r) for r in cursor.fetchall()]

    conn.close()

    print("Recreating database schema...")
    # Delete old database to start clean
    os.remove(DB_PATH)

    # Import db to use init_schema
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    import db

    new_conn = db.connect(DB_PATH)
    db.init_schema(new_conn)
    new_cursor = new_conn.cursor()

    print("Migrating usage_history...")
    for row in old_history:
        cycle_ts, ts = to_cycle_ts_and_str(row['timestamp'])
        new_cursor.execute('''
            INSERT OR REPLACE INTO usage_history (
                source, cycle_ts, timestamp, sessions, messages, days,
                total_cost, avg_cost_per_day, avg_tokens_per_session, median_tokens_per_session,
                input_tokens, output_tokens, cache_read, cache_write
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row.get('source', 'opencode'), cycle_ts, ts, row.get('sessions'), row.get('messages'),
            row.get('days', 0), row.get('total_cost', 0.0), row.get('avg_cost_per_day', 0.0),
            row.get('avg_tokens_per_session', 0.0), row.get('median_tokens_per_session', 0.0),
            row.get('input_tokens'), row.get('output_tokens'), row.get('cache_read'), row.get('cache_write')
        ))

    print("Migrating model_usage...")
    for row in old_model_usage:
        cycle_ts, ts = to_cycle_ts_and_str(row['timestamp'])
        new_cursor.execute('''
            INSERT OR REPLACE INTO model_usage (
                source, cycle_ts, timestamp, model_name, messages,
                input_tokens, output_tokens, cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row.get('source', 'opencode'), cycle_ts, ts, row.get('model_name'), row.get('messages'),
            row.get('input_tokens'), row.get('output_tokens'), row.get('cache_read'), row.get('cache_write'),
            row.get('cost')
        ))

    print("Migrating quota_snapshots...")
    for row in old_quota:
        cycle_ts, ts = to_cycle_ts_and_str(row['timestamp'])
        new_cursor.execute('''
            INSERT OR REPLACE INTO quota_snapshots (
                source, cycle_ts, timestamp, model_group, limit_type,
                used, total, remaining_pct, refreshes_in_seconds
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            row.get('source', 'agy'), cycle_ts, ts, row.get('model_group'), row.get('limit_type'),
            row.get('used'), row.get('total'), row.get('remaining_pct'), row.get('refreshes_in_seconds')
        ))

    print("Migrating collection_status...")
    for row in old_status:
        cycle_ts, ts = to_cycle_ts_and_str(row['timestamp'])
        new_cursor.execute('''
            INSERT OR REPLACE INTO collection_status (
                source, cycle_ts, timestamp, ok, error, duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            row.get('source'), cycle_ts, ts, row.get('ok'), row.get('error'), row.get('duration_ms')
        ))

    print("Migrating meta...")
    for row in old_meta:
        if row['key'] != 'schema_version':
            new_cursor.execute('''
                INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)
            ''', (row['key'], row['value']))

    # Force schema version to 1
    new_cursor.execute('''
        INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '1')
    ''')

    new_conn.commit()
    new_conn.close()
    print("Migration completed successfully!")


if __name__ == '__main__':
    migrate()
