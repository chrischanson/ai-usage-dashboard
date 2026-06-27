# Model Token Tracker — Design Document

## Goal

Track token usage, session stats, and quota limits across three LLM coding tools — Antigravity (AGY CLI/IDE), OpenCode CLI, and Codex CLI (OpenAI) — and display everything in a single real-time dashboard.

## Approach

**No external API costs.** All usage data is extracted from local SQLite databases and command-line output on the user's machine. Quota data comes from a mix of local RPC calls and public API endpoints, but the core tracking has zero external dependencies and no rate limits.

The system uses a **background poll loop** every 10 minutes to collect data from all sources into a local SQLite database. A FastAPI server serves this data to a browser-based frontend that refreshes every 60 seconds.

## Requirements

### Data Sources

| Source | Usage Data | Quota Data |
|---|---|---|
| **AGY** | Reads conversation protobuf blobs from `~/.gemini/antigravity-*/conversations/*.db` | Cloud Code API via local RPC (`RetrieveUserQuotaSummary`) + `loadCodeAssist` for plan |
| **OpenCode** | Runs `opencode stats --models` subprocess | Same subprocess, extracts total cost |
| **Codex (OpenAI)** | Reads `~/.codex/state_5.sqlite` threads table | JWT plan + billing API (if key available) + `logs_2.sqlite` rate limit events |

### API Endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/usage/latest` | Combined latest usage for all sources |
| `GET /api/usage/{source}/latest` | Per-source usage (`agy`, `opencode`, `codex`) |
| `GET /api/usage/{source}/history` | Per-source history series |
| `GET /api/usage/latest?deltas=true` | Model deltas for Rate mode |
| `GET /api/quota/latest` | Combined quota with plan labels |
| `GET /api/quota/{source}/latest` | Per-source quota |

### Frontend Layout

- **Header**: Title + time range buttons + Live pill in one row. No subtitle.
- **Tabs**: All, AGY, OpenCode, Codex (OpenAI). "All" label, not "Combined".
- **Overview + Quota**: Side-by-side below tabs.
- **Overview Cards**: 2×2 grid. Sessions/Messages (same row, `/` separator) | Cache Reads. Input Tokens | Output Tokens.
- **History Chart**: Line chart with zoom/pan. Stacked area in Total mode, individual lines in Rate mode.
- **Model Distribution**: Doughnut chart. Title adapts to mode.
- **Mode Toggle**: Total (cumulative) / Rate (per-period deltas).
- **Time Range**: 1h/6h/1d/1w/1m/3m/all. Affects entire page. Relative to data's latest timestamp, not wall clock.

### Quota Display

- **AGY**: Model groups with progress bars. Plan badge from Cloud Code API (`paidTier.name`).
- **OpenCode**: Total cost only.
- **Codex**: Monthly limit percentage bar + plan badge from JWT. No cost display.

### Security

- All API-sourced strings escaped via `escapeHtml()` before `innerHTML` injection.
- No secrets or keys logged.

### Server

- Uses `start-stop-daemon` for background execution, survives shell exit.
- Python venv at `/tmp/venv/bin/python3`.
- Uvicorn on port 8000, serves static frontend files.
- Poll interval: 600 seconds (10 min).

### Mobile

- Breakpoint at 640px: reduced padding, stacked header, scrollable tabs, single-column layouts, 24-hour time labels.

## System Design

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Data Sources                           │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ OpenCode │  │ AGY Local DB │  │ Codex SQLite DBs │   │
│  │ CLI      │  │ (protobuf)   │  │ (state/logs)     │   │
│  └────┬─────┘  └──────┬───────┘  └────────┬─────────┘   │
│       │               │                    │             │
│       ▼               ▼                    ▼             │
│  parser.py    agy_parser.py      codex_parser.py         │
│       │               │                    │             │
│       └───────────────┼────────────────────┘             │
│                       ▼                                  │
│              Poll Loop (600s interval)                   │
│                       │                                  │
│                       ▼                                  │
│               Database (agy_quota.db)                    │
│              ┌──────────────────────┐                    │
│              │ usage_history        │                    │
│              │ model_usage          │                    │
│              │ quota_snapshots      │                    │
│              └──────────────────────┘                    │
│                       ▲                                  │
│              API Routes (FastAPI)                        │
│                       │                                  │
├───────────────────────┼──────────────────────────────────┤
│                       ▼                                  │
│               Frontend (browser)                         │
│    ┌──────────────────────────────────────┐              │
│    │ index.html + app.js + Chart.js       │              │
│    │ refresh() every 60s                  │              │
│    └──────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Separate parsers per source** — Each data source has its own parser module returning a uniform `(overview, cost_tokens, models)` tuple. Adding a new source means writing a new parser; nothing else changes.

2. **No network calls for tracking** — AGY and Codex usage data comes from local SQLite files. Only quota data hits network APIs. This avoids circular dependency (using LLM quota to track LLM quota) and works offline.

3. **Poll-driven with DB cache** — The 10-minute poll loop amortizes I/O costs across users. The local DB provides time-series history even when sources are temporarily unavailable. The frontend polls the API every 60s for fresh data from the cache.

4. **Quota live enrichment** — Quota endpoints re-fetch live plan data (AGY plan, Codex rate limits) on every API call rather than relying solely on the last DB snapshot. Users see current limits between poll cycles.

5. **Model deltas for Rate mode** — Rate mode computes `current - previous` per model server-side in `get_latest_usage(include_model_deltas)`. Only positive deltas are returned. The frontend switches between `models` (Total) and `model_deltas` (Rate) based on the mode toggle.

6. **Time range relative to data** — `filterByTimeRange()` uses the data's own latest timestamp, not `Date.now()`. This prevents empty charts from clock skew or paused data collection.

7. **Client-side filtering** — History data is cached in the browser after one fetch. Time range and mode changes filter/recompute locally without additional API calls.

8. **Responsive with no framework** — Pure CSS. Glass morphism design with `backdrop-filter`. No Tailwind or Bootstrap. Keeps dependencies minimal.

### Database Schema

Three tables in a local SQLite file (`backend/agy_quota.db`):

- **usage_history**: One row per poll per source. Stores aggregate `sessions`, `messages`, `input_tokens`, `output_tokens`, `cache_read`, `cache_write`.
- **model_usage**: One row per model per poll. Links to `usage_history` via `timestamp + source`. Stores `model_name`, `messages`, `input_tokens`, `output_tokens`, `cache_*`, `cost`.
- **quota_snapshots**: One row per model group per limit type per poll. Stores `used`, `total`, `remaining_pct`, `refreshes_in_seconds`.

### Frontend State Machine

The frontend has 4 independent state variables. Changing any one triggers a recompute:

```
currentSource (tab)  → clears caches, full refresh
timeRange (1h/6h/…)  → filters cached history, recomputes overview
mode (total/rate)    → toggles chart stack vs line + fetches deltas
```

`cachedHistory` and `cachedLatestOverview` are invalidated on tab switch to prevent cross-contamination between sources.

### Verification

A standalone `verify.py` script (146 checks) validates server health, HTML structure, JS functions, CSS rules, all API endpoints, and regression-specific patterns (XSS, cache clearing, date parsing, mobile layout). Run with:

```bash
PYTHONPATH=backend python3 verify.py
```
