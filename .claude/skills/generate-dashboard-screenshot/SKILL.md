---
name: generate-dashboard-screenshot
description: Guidelines and instructions for generating a high-quality screenshot of the AI Usage Dashboard for README.md.
---

# Generate Dashboard Screenshot

All paths below are relative to the repository root.

Use this skill when you need to regenerate the screenshot of the AI Usage Dashboard at `docs/screenshot.png`.

> ⚠️ **NEVER seed or point the seeder at the live database `backend/usage.db`.**
> The seeder deletes its target and fills it with fake data. On 2026-07-03 a
> run against the live DB destroyed a week of real usage history (recovered
> only because a backup existed). Always seed a throwaway file via
> `USAGE_DB_PATH` and run a *separate* server instance against it. Restore
> every temporary code edit (e.g. in `backend/api.py`) before finishing —
> use `git diff` to confirm nothing is left behind.

## Workflow

### 1. Seed a throwaway database
Seed 7 days of realistic demo history across all four sources (AGY, Claude, OpenCode, Codex) into a **temporary** SQLite file — never the live one.

Template seeding script (refuses to run without `USAGE_DB_PATH`, and refuses paths that look like the live DB):
[seed_dashboard_screenshot.py](resources/seed_dashboard_screenshot.py)

```bash
export USAGE_DB_PATH=/tmp/screenshot-seed.db
python3 .claude/skills/generate-dashboard-screenshot/resources/seed_dashboard_screenshot.py
# Then launch the dashboard against the same USAGE_DB_PATH on a spare port:
USAGE_DB_PATH=/tmp/screenshot-seed.db USAGE_PORT=8010 ./run.sh
```

### 2. Inject Mock Quota Data in backend/api.py
To avoid timeouts or connection errors from real external/local APIs, temporarily modify `backend/api.py` to return mock quota limits when `USAGE_MOCK_ALL=1` is specified.

Insert the `_mock_quota_fetch` function and modify `_get_cached_quota` in `backend/api.py`:

```python
def _mock_quota_fetch(source: str):
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    future_5h = (now_utc + timedelta(hours=3)).isoformat()
    future_7d = (now_utc + timedelta(days=2)).isoformat()

    if source == 'agy':
        return {
            'plan': 'Gemini Advanced Plan',
            'gemini_models': {
                'weekly_limit': {'used': 42.5, 'total': 100.0, 'remaining_pct': 57.5, 'refreshes_in': 18000},
                'five_hour_limit': {'used': 15.0, 'total': 100.0, 'remaining_pct': 85.0, 'refreshes_in': 3600}
            },
            'claude_gpt_models': {
                'weekly_limit': {'used': 75.0, 'total': 100.0, 'remaining_pct': 25.0, 'refreshes_in': 45000},
                'five_hour_limit': {'used': 60.0, 'total': 100.0, 'remaining_pct': 40.0, 'refreshes_in': 7200}
            }
        }
    elif source == 'codex':
        return {
            'plan_type': 'chatgptplusplan',
            'primary_used_pct': 42.5,
            'resets_in_seconds': 1800
        }
    elif source == 'opencode':
        return {
            'total_cost': 45.80,
            'cost_by_model': {'claude-sonnet-4': 38.20, 'claude-haiku-3.5': 7.60}
        }
    elif source == 'claude':
        return {
            'subscription_type': 'pro',
            'five_hour': {'utilization': 35.0, 'resets_at': future_5h},
            'seven_day': {'utilization': 45.0, 'resets_at': future_7d},
            'limits': [
                {'kind': 'weekly_scoped', 'scope': {'model': {'display_name': 'Claude 3.5 Sonnet'}}, 'percent': 55.0, 'resets_at': future_7d},
                {'kind': 'weekly_scoped', 'scope': {'model': {'display_name': 'Claude 3 Opus'}}, 'percent': 15.0, 'resets_at': future_7d}
            ]
        }
    return None

def _get_cached_quota(source: str, fetcher, force: bool = False):
    if os.environ.get('USAGE_MOCK_ALL') == '1':
        return _mock_quota_fetch(source)
    # original logic...
```

### 3. Run the Backend Server
Start the backend server locally using the project's virtual environment:
```bash
USAGE_MOCK_ALL=1 USAGE_PORT=8000 USAGE_HOST=127.0.0.1 venv/bin/python backend/main.py
```

### 4. Capture Headless Screenshot
Run Google Chrome in headless mode with a delayed budget to allow Chart.js animations to complete:
```bash
google-chrome --headless --disable-gpu --window-size=1280,1000 --screenshot=docs/screenshot.png --virtual-time-budget=10000 http://127.0.0.1:8000/
```

### 5. Cleanup
Terminate the backend server and discard the temporary modifications in `backend/api.py`:
```bash
git checkout backend/api.py
```
