"""Seed usage.db with one cycle of test data for CI verification."""
import os
import sys
import time
import json

# Ensure we can import from backend
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import connect, init_schema, insert_usage, insert_quota, record_status

CYCLE_TS = (int(time.time()) // 600) * 600

AGY_MODELS = [
    {"model_name": "gemini-2.5-pro", "messages": 12, "input_tokens": 45000, "output_tokens": 8200, "cache_read": 12000, "cache_write": 3000, "cost": 0.45},
    {"model_name": "gemini-2.5-flash", "messages": 8, "input_tokens": 18000, "output_tokens": 4100, "cache_read": 5000, "cache_write": 1000, "cost": 0.08},
]
AGY_OVERVIEW = {
    "sessions": 20, "messages": 20, "input_tokens": 63000,
    "output_tokens": 12300, "cache_read": 17000, "cache_write": 4000,
}

OPENCODE_MODELS = [
    {"model_name": "claude-sonnet-4", "messages": 15, "input_tokens": 52000, "output_tokens": 9100, "cache_read": 0, "cache_write": 0, "cost": 0.62},
    {"model_name": "claude-haiku-3.5", "messages": 7, "input_tokens": 14000, "output_tokens": 3800, "cache_read": 0, "cache_write": 0, "cost": 0.04},
]
OPENCODE_OVERVIEW = {
    "sessions": 22, "messages": 22, "input_tokens": 66000,
    "output_tokens": 12900, "cache_read": 0, "cache_write": 0,
}

CODEX_MODELS = [
    {"model_name": "gpt-4o", "messages": 10, "input_tokens": 38000, "output_tokens": 7200, "cache_read": 0, "cache_write": 0, "cost": 0.38},
    {"model_name": "o3-mini", "messages": 5, "input_tokens": 11000, "output_tokens": 2600, "cache_read": 0, "cache_write": 0, "cost": 0.03},
]
CODEX_OVERVIEW = {
    "sessions": 15, "messages": 15, "input_tokens": 49000,
    "output_tokens": 9800, "cache_read": 0, "cache_write": 0,
}

AGY_QUOTA = {
    "gemini_models": {
        "monthly_quota": {"used": 450000, "total": 1000000, "remaining_pct": 55.0, "refreshes_in_seconds": 0},
        "daily_quota": {"used": 25000, "total": 100000, "remaining_pct": 75.0, "refreshes_in_seconds": 0},
    },
    "claude_gpt_models": {
        "monthly_quota": {"used": 200000, "total": 500000, "remaining_pct": 60.0, "refreshes_in_seconds": 0},
        "daily_quota": {"used": 15000, "total": 50000, "remaining_pct": 70.0, "refreshes_in_seconds": 0},
    },
}

OPENCODE_QUOTA = {
    "opencode": {
        "total_cost": {"used": 45.80, "total": 100.0, "remaining_pct": 54.2, "refreshes_in_seconds": 0},
    },
}

CODEX_QUOTA = {
    "openai": {
        "rate_limit": {
            "remaining_pct": 57.5,
            "used": 42.5,
            "total": 100.0,
            "refreshes_in_seconds": 0,
        },
        "cost": {
            "used": 5.25,
            "total": 10.0,
            "remaining": 4.75,
        },
    },
}


def main():
    db_path = os.getenv("USAGE_DB_PATH") or os.path.join(os.path.dirname(__file__), "usage.db")
    print(f"Seeding test data into {db_path}")

    conn = connect(db_path)
    init_schema(conn)

    # Seed usage + models for each source
    insert_usage(conn, "agy", CYCLE_TS, AGY_OVERVIEW, AGY_MODELS)
    print("  agy: inserted usage + 2 models")

    insert_usage(conn, "opencode", CYCLE_TS, OPENCODE_OVERVIEW, OPENCODE_MODELS)
    print("  opencode: inserted usage + 2 models")

    insert_usage(conn, "codex", CYCLE_TS, CODEX_OVERVIEW, CODEX_MODELS)
    print("  codex: inserted usage + 2 models")

    # Seed quota snapshots
    insert_quota(conn, "agy", CYCLE_TS, AGY_QUOTA)
    print("  agy: inserted quota (gemini_models + claude_gpt_models)")

    insert_quota(conn, "opencode", CYCLE_TS, OPENCODE_QUOTA)
    print("  opencode: inserted quota (total_cost)")

    insert_quota(conn, "codex", CYCLE_TS, CODEX_QUOTA)
    print("  codex: inserted quota (monthly_limit)")

    # Seed collection status (all ok)
    for src in ("agy", "opencode", "codex"):
        record_status(conn, src, CYCLE_TS, True, None, 1200)

    conn.close()
    print(f"Done. Data seeded at cycle_ts={CYCLE_TS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
