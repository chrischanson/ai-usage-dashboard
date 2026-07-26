"""Seed usage.db with beautiful 7-day history for the README screenshot."""
import os
import sys
import time
import random
from datetime import datetime, timezone, timedelta

# Ensure we can import from backend
# resources/ -> skill -> skills -> .claude -> repo root -> backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "backend"))

try:
    from db import connect, init_schema, record_observation, record_quota, record_status
except ImportError:
    # Try importing directly if run from public_projects/ai-usage-dashboard
    sys.path.insert(0, os.path.dirname(__file__))
    from db import connect, init_schema, record_observation, record_quota, record_status

from types import SimpleNamespace


def _seed_usage(conn, src, cycle_ts, overview, models_list):
    record_observation(conn, src, cycle_ts, SimpleNamespace(models=models_list, **overview))


def main():
    # SAFETY: this script DELETES its target and fills it with FAKE data.
    # It must never touch the live dashboard database (backend/usage.db).
    # On 2026-07-03 a run against the live DB destroyed a week of real
    # history; hence the hard requirements below.
    db_path = os.getenv("USAGE_DB_PATH")
    if not db_path:
        print("ERROR: set USAGE_DB_PATH to an explicit throwaway path (e.g. /tmp/screenshot.db).", file=sys.stderr)
        print("Refusing to guess a target for a destructive fake-data seeder.", file=sys.stderr)
        return 1
    db_path = os.path.abspath(db_path)
    if os.path.basename(os.path.dirname(db_path)) == "backend" or os.path.basename(db_path) == "usage.db":
        print(f"ERROR: {db_path} looks like a live dashboard database. Refusing.", file=sys.stderr)
        return 1
    print(f"Seeding screenshot data into {db_path}")

    # Remove existing db to have a clean start
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  Removed existing database.")

    conn = connect(db_path)
    init_schema(conn)

    # 7 days of history, 10-minute cycles
    # 7 * 24 * 6 = 1008 cycles
    num_cycles = 1008
    now_ts = int(time.time())
    # Aligned to 10-min cycle
    end_cycle = (now_ts // 600) * 600
    start_cycle = end_cycle - (num_cycles * 600)

    # Starting values
    state = {
        "agy": {
            "sessions": 5, "messages": 10, "input_tokens": 15000, "output_tokens": 3000, "cache_read": 5000, "cache_write": 1000,
            "models": {
                "gemini-2.5-pro": {"messages": 7, "input_tokens": 11000, "output_tokens": 2200, "cache_read": 4000, "cache_write": 800, "cost": 0.15},
                "gemini-2.5-flash": {"messages": 3, "input_tokens": 4000, "output_tokens": 800, "cache_read": 1000, "cache_write": 200, "cost": 0.02}
            }
        },
        "claude": {
            "sessions": 8, "messages": 22, "input_tokens": 25000, "output_tokens": 6000, "cache_read": 10000, "cache_write": 2000,
            "models": {
                "claude-3.5-sonnet": {"messages": 18, "input_tokens": 20000, "output_tokens": 4800, "cache_read": 8000, "cache_write": 1600, "cost": 0.32},
                "claude-3-opus": {"messages": 4, "input_tokens": 5000, "output_tokens": 1200, "cache_read": 2000, "cache_write": 400, "cost": 0.25}
            }
        },
        "opencode": {
            "sessions": 6, "messages": 15, "input_tokens": 18000, "output_tokens": 4000, "cache_read": 0, "cache_write": 0,
            "models": {
                "claude-sonnet-4": {"messages": 12, "input_tokens": 15000, "output_tokens": 3200, "cache_read": 0, "cache_write": 0, "cost": 0.18},
                "claude-haiku-3.5": {"messages": 3, "input_tokens": 3000, "output_tokens": 800, "cache_read": 0, "cache_write": 0, "cost": 0.02}
            }
        },
        "codex": {
            "sessions": 4, "messages": 12, "input_tokens": 12000, "output_tokens": 2800, "cache_read": 0, "cache_write": 0,
            "models": {
                "gpt-4o": {"messages": 8, "input_tokens": 9000, "output_tokens": 2000, "cache_read": 0, "cache_write": 0, "cost": 0.11},
                "o3-mini": {"messages": 4, "input_tokens": 3000, "output_tokens": 800, "cache_read": 0, "cache_write": 0, "cost": 0.03}
            }
        }
    }

    print(f"Generating cycles from {start_cycle} to {end_cycle}...")

    # Seed random for deterministic beauty
    random.seed(42)

    for step in range(num_cycles):
        cycle_ts = start_cycle + (step * 600)
        
        # Decide if we have activity in this cycle (e.g., higher activity during "work hours")
        # Compute local hour of the cycle to simulate developer workday
        cycle_dt = datetime.fromtimestamp(cycle_ts, tz=timezone.utc)
        hour = cycle_dt.hour
        
        # Workday has higher probability of usage
        is_work_hour = 8 <= hour <= 19
        usage_prob = 0.12 if is_work_hour else 0.02

        for src, data in state.items():
            if random.random() < usage_prob:
                # Add usage
                session_inc = 1 if random.random() < 0.08 else 0
                msg_inc = random.randint(1, 3)
                
                data["sessions"] += session_inc
                data["messages"] += msg_inc

                # Distribute message increment among models
                models = list(data["models"].keys())
                # First model is main model (e.g. pro/sonnet/4o)
                main_model = models[0]
                sub_model = models[1]
                
                # Main model gets ~80% of activity
                for _ in range(msg_inc):
                    model_choice = main_model if random.random() < 0.8 else sub_model
                    
                    # Generate inputs & outputs
                    in_tokens = random.randint(800, 3500)
                    out_tokens = random.randint(150, 750)
                    
                    data["input_tokens"] += in_tokens
                    data["output_tokens"] += out_tokens
                    
                    data["models"][model_choice]["messages"] += 1
                    data["models"][model_choice]["input_tokens"] += in_tokens
                    data["models"][model_choice]["output_tokens"] += out_tokens
                    
                    # Cache read/write for AGY & Claude
                    if src in ("agy", "claude"):
                        cread = random.randint(200, 1500) if random.random() < 0.6 else 0
                        cwrite = random.randint(100, 500) if random.random() < 0.3 else 0
                        
                        data["cache_read"] += cread
                        data["cache_write"] += cwrite
                        data["models"][model_choice]["cache_read"] += cread
                        data["models"][model_choice]["cache_write"] += cwrite
                        
                    # Calculate cost (rough estimate)
                    if "pro" in model_choice or "sonnet" in model_choice or "gpt-4o" in model_choice:
                        cost = (in_tokens * 3.0 / 1e6) + (out_tokens * 15.0 / 1e6)
                    else: # flash / haiku / o3-mini
                        cost = (in_tokens * 0.25 / 1e6) + (out_tokens * 1.25 / 1e6)
                    data["models"][model_choice]["cost"] += cost

            # Insert usage_history & model_usage rows for this cycle
            overview = {
                "sessions": data["sessions"],
                "messages": data["messages"],
                "input_tokens": data["input_tokens"],
                "output_tokens": data["output_tokens"],
                "cache_read": data["cache_read"],
                "cache_write": data["cache_write"]
            }
            
            models_list = []
            for name, mdata in data["models"].items():
                models_list.append({
                    "model_name": name,
                    "messages": mdata["messages"],
                    "input_tokens": mdata["input_tokens"],
                    "output_tokens": mdata["output_tokens"],
                    "cache_read": mdata["cache_read"],
                    "cache_write": mdata["cache_write"],
                    "cost": round(mdata["cost"], 4)
                })

            _seed_usage(conn, src, cycle_ts, overview, models_list)

    # Insert final quota snapshots
    print("Inserting final quota snapshots...")
    
    # AGY
    record_quota(conn, "agy", end_cycle, [
        {"model_group": "gemini_models", "limit_type": "weekly_limit", "used": 42.5, "total": 100.0, "remaining_pct": 57.5, "refreshes_in_seconds": 18000},
        {"model_group": "gemini_models", "limit_type": "five_hour_limit", "used": 15.0, "total": 100.0, "remaining_pct": 85.0, "refreshes_in_seconds": 3600},
        {"model_group": "claude_gpt_models", "limit_type": "weekly_limit", "used": 75.0, "total": 100.0, "remaining_pct": 25.0, "refreshes_in_seconds": 45000},
        {"model_group": "claude_gpt_models", "limit_type": "five_hour_limit", "used": 60.0, "total": 100.0, "remaining_pct": 40.0, "refreshes_in_seconds": 7200}
    ])
    
    # Claude
    record_quota(conn, "claude", end_cycle, [
        {"model_group": "session", "limit_type": "five_hour", "used": 35.0, "total": 100.0, "remaining_pct": 65.0, "refreshes_in_seconds": 14400},
        {"model_group": "weekly", "limit_type": "all_models", "used": 48.0, "total": 100.0, "remaining_pct": 52.0, "refreshes_in_seconds": 172800},
        {"model_group": "weekly", "limit_type": "Claude 3.5 Sonnet", "used": 58.0, "total": 100.0, "remaining_pct": 42.0, "refreshes_in_seconds": 172800},
        {"model_group": "weekly", "limit_type": "Claude 3 Opus", "used": 18.0, "total": 100.0, "remaining_pct": 82.0, "refreshes_in_seconds": 172800}
    ])
    
    # OpenCode
    record_quota(conn, "opencode", end_cycle, [
        {"model_group": "opencode", "limit_type": "total_cost", "used": 45.80, "total": 100.0, "remaining_pct": 54.2, "refreshes_in_seconds": 0}
    ])
    
    # Codex
    record_quota(conn, "codex", end_cycle, [
        {"model_group": "openai", "limit_type": "rate_limit", "used": 42.5, "total": 100.0, "remaining_pct": 57.5, "refreshes_in_seconds": 1800}
    ])

    # Record active/ok status for all sources
    for src in ("agy", "claude", "opencode", "codex"):
        record_status(conn, src, 'usage', end_cycle, True, None, 150.0)

    conn.close()
    print(f"Successfully seeded {num_cycles} cycles of dashboard history up to cycle_ts={end_cycle}.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
