import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "agy_quota.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
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
            model_name TEXT,
            messages INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_read INTEGER,
            cache_write INTEGER,
            cost REAL
        )
    ''')
    conn.commit()
    conn.close()

def insert_usage(overview, cost_tokens, models):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO usage_history (
            sessions, messages, days, total_cost, avg_cost_per_day,
            avg_tokens_per_session, median_tokens_per_session,
            input_tokens, output_tokens, cache_read, cache_write
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
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
        cost_tokens.get('Cache Write', 0)
    ))
    
    for m in models:
        cursor.execute('''
            INSERT INTO model_usage (
                model_name, messages, input_tokens, output_tokens,
                cache_read, cache_write, cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            m['name'],
            m.get('Messages', 0),
            m.get('Input Tokens', 0),
            m.get('Output Tokens', 0),
            m.get('Cache Read', 0),
            m.get('Cache Write', 0),
            m.get('Cost', 0.0)
        ))
        
    conn.commit()
    conn.close()

def get_latest_usage():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM usage_history ORDER BY timestamp DESC LIMIT 1")
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
        
    res = dict(row)
    
    cursor.execute("SELECT * FROM model_usage WHERE timestamp = ? ORDER BY input_tokens DESC", (res['timestamp'],))
    models = [dict(r) for r in cursor.fetchall()]
    res['models'] = models
    
    conn.close()
    return res

def get_history_series(limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM usage_history ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows[::-1]
