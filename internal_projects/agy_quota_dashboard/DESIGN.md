# Agent Quota Monitor — Design Document

## Goal

Track token usage, session stats, and quota limits across three LLM coding
agents — **Antigravity (AGY CLI/IDE)**, **OpenCode CLI**, and **Codex CLI
(OpenAI)** — and surface them in a single, real-time dashboard that works well
on desktop and mobile.

The system is a **local, lightweight, robust** monitoring tool: one process,
one SQLite file, a small set of dependencies. It must run unattended for weeks
without silent failures, and each component must be small enough that an agent
can implement and verify it in isolation.

## Non-Goals

- Multi-tenant, remote, or cloud deployment. Single user, single host.
- Real-time push (WebSockets/SSE). A 60s frontend poll is sufficient.
- Calling vendor APIs for usage. Usage stays local-first (files + CLI output).
- A frontend framework (React/Vue) or CSS framework (Tailwind/Bootstrap).
- Authentication or access control.

## Simplicity Constraints (read before adding anything)

This is a small tool. To keep it implementable and verifiable, the design
**deliberately avoids**: ORMs, a migrations framework, parallel/async polling,
per-source backoff schedulers, conditional requests (ETag/304), gzip/CORS
middleware, message queues, and protobuf libraries (parse the bytes we need
directly). The 10-minute poll interval is the natural rate limiter; do not add
retry/backoff state on top of it. If a feature here is not required by the
*Requirements*, it does not belong in the implementation.

## Requirements

### Functional

#### Data Sources

| Source | Usage Data | Quota Data |
|---|---|---|
| **AGY** | Conversation protobuf blobs from `~/.gemini/antigravity-*/conversations/*.db` | Cloud Code API via local RPC (`RetrieveUserQuotaSummary`) + `loadCodeAssist` for plan (`paidTier.name`) |
| **OpenCode** | `opencode stats --models` subprocess output | Same subprocess; total cost extracted |
| **Codex (OpenAI)** | `~/.codex/state_5.sqlite` threads table | JWT plan (`chatgpt_plan_type`) + billing API (optional, if key present) + `logs_2.sqlite` rate-limit events (`codex.rate_limits`) |

Every source is **optional and isolated**: if a source's files/commands are
absent or fail, the rest of the system keeps working and reports that source
as unavailable rather than crashing.

#### API Endpoints

| Endpoint | Method | Returns | Notes |
|---|---|---|---|
| `/api/usage/latest` | GET | Combined latest usage for all sources | `?deltas=true` adds model deltas for Rate mode |
| `/api/usage/{source}/latest` | GET | Per-source usage (`agy`/`opencode`/`codex`) | 404 on unknown source |
| `/api/usage/{source}/history` | GET | Per-source history series | optional `?limit=` cap |
| `/api/quota/latest` | GET | Combined quota with plan labels | live-enriched, falls back to last snapshot |
| `/api/quota/{source}/latest` | GET | Per-source quota | 404 on unknown source |
| `/health` | GET | Liveness — `{ "status": "ok" }`, always 200 if running | — |
| `/ready` | GET | Readiness — 200 once DB is reachable and ≥1 poll succeeded; else 503 | — |
| `/metrics` | GET | Operational metrics (JSON) | per-source last success/error, poll count, DB size |

Data endpoints return the resource directly on success and a uniform error
envelope otherwise (see *API Specification*).

#### Frontend Layout

- **Header**: Title "Model Usage Dashboard" + time range buttons + Live pill in one row. No subtitle.
- **Tabs**: All, AGY, OpenCode, Codex (OpenAI). Tab label is "All", not "Combined (All)".
- **Overview + Quota**: Side-by-side in `.stats-row` flex container.
- **Overview Cards**: 2×2 grid. Row 1: Sessions/Messages (same row, same size, `/` separator) | Cache Reads. Row 2: Input Tokens | Output Tokens.
- **History Chart**: Stacked area (Total mode) or individual lines (Rate mode).
- **Model Distribution**: Donut chart. Title adapts to mode.
- **Mode Toggle**: Total/Rate. Affects history chart + model chart + overview cards.
- **Time Range**: 1h/6h/1d/1w/1m/3m/all. Affects entire page. Relative to data's latest timestamp, not `Date.now()`.
- **Model Details Panel**: Shows per-model token/session breakdown for the selected time range. When range is "all", shows cumulative totals from latest snapshot. When a specific range is selected, computes deltas between the earliest and latest history entries in that range.

#### Quota Display

- **AGY**: Model groups with limit bars. Plan badge dynamic from API (`paidTier.name`).
- **OpenCode**: Total cost display.
- **Codex**: Monthly limit % bar + plan badge only. No cost display. Plan from JWT (`chatgpt_plan_type`).

### Non-Functional (design targets)

| Concern | Target |
|---|---|
| Poll cycle latency | Bounded by per-source timeouts (subprocess + network), not by hangs |
| Availability | No silent crashes; a failed source degrades, never halts the loop |
| Data retention | Configurable; default 90 days; pruned once per poll cycle |
| Dependencies | Python stdlib + FastAPI + uvicorn; Chart.js vendored locally |
| Footprint | Single process, single SQLite file, modest idle memory |
| Responsiveness | Usable on desktop and mobile (single 640px breakpoint) |

## System Design

### Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Data Sources (each isolated, optional)                     │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ OpenCode │  │ AGY Local DB │  │ Codex SQLite DBs     │  │
│  │ CLI      │  │ (protobuf)   │  │ (state/logs)         │  │
│  └────┬─────┘  └──────┬───────┘  └──────────┬───────────┘  │
│       ▼               ▼                     ▼              │
│  parsers/opencode  parsers/agy       parsers/codex         │
│       └───────────────┴─────────────────────┘              │
│              (overview, cost_tokens, models)                │
│                       ▼                                     │
│   poller.py (600s, sequential, per-source try/except)       │
│     ├── quota.py (live enrichment, fallback to snapshot)    │
│     └── writes usage + status; prunes old rows              │
│                       ▼                                     │
│        db.py → agy_quota.db (WAL, idempotent schema)        │
│     usage_history · model_usage · quota_snapshots ·         │
│     collection_status · meta                                │
│                       ▲                                     │
│        api.py (FastAPI: routes, errors, schemas, static)    │
│              /health · /ready · /metrics                    │
├───────────────────────┼────────────────────────────────────┤
│                       ▼                                     │
│   Frontend: index.html + styles.css + app.js + Chart.js     │
│   refresh() every 60s; loading/error/empty/stale states     │
└────────────────────────────────────────────────────────────┘
```

### Data Flow

1. `poller.py` wakes every 600s (configurable).
2. For each source **sequentially**, run its parser inside a `try/except`.
   Subprocess/network steps have timeouts; local SQLite reads rely on
   `busy_timeout`. On success, write usage rows; on failure, write only a
   `collection_status` row. One source never aborts the cycle.
3. `quota.py` performs live enrichment (AGY plan, Codex rate limits) with its
   own timeouts; on failure the API serves the last snapshot marked `stale`.
4. `db.py` prunes rows older than the retention window once per cycle.
5. `api.py` reads from the DB (re-running live enrichment for quota endpoints)
   and returns the resource or a uniform error envelope.
6. The frontend fetches on load and every 60s, recomputes locally on
   tab/range/mode changes, and shows loading/error/empty/stale states.

## Backend Module Breakdown

Ten cohesive modules. Each has one responsibility, an explicit contract, and a
unit test. A module may consume earlier ones only through the stated contract.

| Module | Responsibility | Contract (signatures) | Verify (unit) |
|---|---|---|---|
| `config.py` | Load + validate config from env; configure JSON logging | `load_config() -> Config`; `setup_logging(level)` | Defaults, env override, invalid value rejected; log line is valid JSON |
| `db.py` | Connection + pragmas + idempotent schema + CRUD + prune | `connect(path)`, `init_schema(conn)`, `insert_usage(conn, source, ts, overview, models)`, `latest_usage(conn, source?)`, `history(conn, source, limit)`, `insert_quota(conn, source, ts, rows)`, `latest_quota(conn, source)`, `record_status(conn, source, ok, err, ms)`, `metrics(conn)`, `prune(conn, days)` | Schema idempotent; pragmas applied (WAL, FK on); insert/read round-trips; prune removes only old rows |
| `parsers/base.py` | Parser contract + shared types/helpers | `Parser.parse(cfg) -> (overview, cost_tokens, models)`; raises `SourceUnavailable` | Contract shape; helper unit tests |
| `parsers/opencode.py` | OpenCode usage parser (subprocess) | implements `Parser` | Fixture stdout → expected tuple; missing binary → `SourceUnavailable` |
| `parsers/agy.py` | AGY usage parser (local DB / protobuf bytes) | implements `Parser` | Fixture DB → expected tuple; missing files → `SourceUnavailable` |
| `parsers/codex.py` | Codex usage parser (local DB) | implements `Parser` | Fixture DB → expected tuple; missing files → `SourceUnavailable` |
| `quota.py` | Live quota enrichment + fallback | `collect(source, cfg) -> QuotaSnapshot \| None` | Mock RPC → snapshot; timeout → None (caller falls back) |
| `poller.py` | One poll cycle + loop + thread lifecycle | `run_once(cfg, conn)`, `start(cfg)`, `stop()` | One failing source doesn't block others; statuses recorded; prune called |
| `api.py` | FastAPI app: routes, error handlers, response schemas, static mount | `create_app(cfg) -> FastAPI` | Routes return correct shapes/codes; `/ready` 503 before first poll, 200 after; error envelope; static served |
| `main.py` | Entry point: init DB, start poller thread, run uvicorn, graceful shutdown | `main()` | Smoke: boots, `/health` 200, clean SIGTERM |

**Parser contract**: every parser returns `(overview, cost_tokens, models)`
where `overview = {sessions, messages, input_tokens, output_tokens,
cache_read, cache_write}` and `models` is a list of per-model rows. On any
missing file/command or parse failure it raises `SourceUnavailable`. This
tuple is the single seam for adding sources — a new source needs only a new
parser module and one registry line.

> `db.py` and `api.py` are the two larger modules but each owns a single
> concern and is fully covered by round-trip / endpoint tests. Split them only
> if they actually grow unwieldy; do not pre-split.

## Data Model

Single SQLite file (`backend/agy_quota.db`). Pragmas set in `db.connect()`:
`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
`busy_timeout=5000`. Schema created idempotently with `CREATE TABLE IF NOT
EXISTS`; a one-row `meta(schema_version)` table records the version. Changes
are additive; a breaking change bumps the version and is documented as a
manual step (no migration runner).

- **usage_history**: one row per poll per source. `id`, `source`, `timestamp`,
  `sessions`, `messages`, `input_tokens`, `output_tokens`, `cache_read`,
  `cache_write`. Index `(source, timestamp)`.
- **model_usage**: one row per model per poll, linked via `(timestamp,
  source)`. `source`, `timestamp`, `model_name`, `messages`, `input_tokens`,
  `output_tokens`, `cache_read`, `cache_write`, `cost`. Index `(source,
  timestamp, model_name)`.
- **quota_snapshots**: one row per model group per limit type per poll.
  `source`, `timestamp`, `model_group`, `limit_type`, `used`, `total`,
  `remaining_pct`, `refreshes_in_seconds`. Index `(source, timestamp)`.
- **collection_status**: per-source health. `source`, `timestamp`, `ok`,
  `error` (nullable), `duration_ms`. Drives `/ready`, `/metrics`, and the
  frontend's per-source availability indicator.
- **meta**: `schema_version` and other small key/values.

**Retention**: `db.prune(conn, retention_days)` runs once per poll cycle (a
cheap `DELETE` by timestamp) to bound DB growth.

## Poll Loop & Error Handling

- **Per-source isolation**: each parser/collector call is wrapped in its own
  `try/except`. A failure writes a `collection_status` row and never aborts
  the cycle.
- **Timeouts where hangs happen**: subprocess calls (`opencode stats`) use
  `subprocess.run(timeout=…)`; network calls (quota RPC, billing API) use a
  request timeout. Local SQLite reads rely on `busy_timeout`. No artificial
  timeout wrappers around plain file reads.
- **No backoff state**: the 10-minute interval is the rate limiter. A failing
  source is simply retried next cycle.
- **Partial writes**: each source's usage rows are written in their own
  transaction; a failed source writes only a status row.
- **Quota fallback**: if `quota.collect()` returns `None`/raises, the API
  serves the last `quota_snapshots` row annotated `stale: true`.
- **Lifecycle**: the poller runs in a background thread with a
  `threading.Event` so `main.py` stops it cleanly on SIGTERM.

## API Specification

### Envelope

Success returns the resource object directly. Errors return:

```json
{ "error": { "code": "source_unknown", "message": "unknown source 'foo'" } }
```

### Status Codes

| Condition | Code |
|---|---|
| Unknown source | 404 (`source_unknown`) |
| No data yet / not ready | 503 (`not_ready`) |
| DB unavailable | 503 (`storage_unavailable`) |
| Quota live fetch failed, snapshot served | 200 + `stale: true` |
| Unexpected | 500 (`internal`) |

### Caching

- `Cache-Control: no-store` on data endpoints (data changes each poll).
- WAL lets API reads run concurrently with the poller's write transaction.

## Observability

- **`/health`** — liveness; always 200 while the server runs.
- **`/ready`** — 200 only when the DB is reachable and `collection_status` has
  at least one `ok` row; else 503.
- **`/metrics`** — JSON with, per source, `last_success_at`, `last_error`,
  `last_duration_ms`; plus `total_polls` and `db_size_bytes`.
- **Logging** — structured JSON lines to stdout (`level`, `event`, `source`,
  `ts`, `duration_ms`). No secrets/keys ever logged. Full tracebacks only at
  `DEBUG`.

## Configuration

`config.py` reads environment variables with validated defaults (no `.env`
parser, no extra dependency):

| Key | Default | Purpose |
|---|---|---|
| `AQM_DB_PATH` | `backend/agy_quota.db` | SQLite location |
| `AQM_POLL_INTERVAL` | `600` | Seconds between polls |
| `AQM_SUBPROCESS_TIMEOUT` | `20` | Timeout for CLI subprocess calls |
| `AQM_NETWORK_TIMEOUT` | `10` | Timeout for quota/network calls |
| `AQM_RETENTION_DAYS` | `90` | History pruning window |
| `AQM_HOST` | `0.0.0.0` | Bind host (`127.0.0.1` to avoid LAN exposure) |
| `AQM_PORT` | `8000` | Bind port |
| `AQM_LOG_LEVEL` | `INFO` | Logging level |

Invalid values fail fast on load with a clear message.

## Frontend Architecture

Three files, matching the existing layout: `index.html`, `styles.css`,
`app.js` (Chart.js vendored locally). `verify.py` checks for the presence of
functions and CSS rules, so these may stay in one `app.js`/`styles.css` or be
split later without affecting verification. `app.js` is organized into clearly
named, independently testable sections:

| Section | Functions (names verify.py checks) | Responsibility |
|---|---|---|
| Utils | `escapeHtml()`, `formatNumber()`, `formatTime()` | Escaping + compact number/time formatting |
| API client | `fetchJSON(path)` | Fetch, parse envelope, surface errors, detect offline |
| State | `setSource()`, `setRange()`, `setMode()` | Hold `currentSource`/`timeRange`/`mode`; invalidate caches on tab switch |
| Render | `renderHeader()`, `renderTabs()`, `renderOverview()`, `renderQuota()`, `renderHistory()`, `renderModelDist()` | Paint each region from cached data |
| States | `renderLoading()`, `renderError()`, `renderEmpty()`, `updateStaleBadge()` | Loading/error/empty/stale UX |
| Loop | `refresh()`, `startRefreshLoop()` | 60s refresh; stale detection; offline reconnect |
| Bootstrap | `init()` | Wire state → render → loop |

### Frontend State Machine

Three independent state variables; changing one triggers a targeted recompute:

```
source (tab)      → invalidates caches, full refresh (fetch)
range (1h/6h/…)   → filters cached history, recomputes overview (no fetch)
mode (total/rate) → toggles chart stack↔line + uses model_deltas (no fetch)
```

`cachedHistory` and `cachedLatestOverview` are cleared on tab switch to prevent
cross-source contamination. Range and mode changes are computed locally from
cached data without extra API calls.

### UX States (all required)

- **Loading**: skeleton placeholders sized to the final layout (no layout shift).
- **Error**: non-blocking banner with the message and a Retry button; the last
  good data stays on screen until a successful refresh replaces it.
- **Empty**: friendly empty state with guidance when a source has no data.
- **Stale**: "Updated Xm ago" badge, amber past a threshold, red when older;
  driven by the data's timestamp, not wall clock.
- **Offline**: banner when a fetch fails on the network; auto-retries on the
  normal loop and clears on reconnect.

## Frontend UX & Accessibility

- **Responsive**: single 640px breakpoint. Mobile: stacked header, scrollable
  tabs, single-column `.stats-row`, 24-hour time labels, reduced padding.
- **Touch targets**: interactive controls ≥ 44×44px on mobile.
- **Keyboard**: tabs and range buttons reachable and operable via keyboard with
  a visible focus ring; mode toggle keyboard-operable.
- **ARIA**: tabs use `role="tablist"/"tab"/"tabpanel"` with `aria-selected`;
  the Live/stale pill uses `aria-live="polite"`.
- **Color**: text meets AA contrast (4.5:1); status colors are paired with text
  or an icon, never color-only.
- **Motion**: `prefers-reduced-motion` disables chart animations and
  transitions.

## Security

- All API-sourced strings escaped via `escapeHtml()` before any `innerHTML`.
- No secrets or keys logged or returned (including `/metrics`).
- **CSP** header on the page: `default-src 'self'; style-src 'self'
  'unsafe-inline'`. Chart.js is vendored locally so no CDN/SRI is needed.
- Request validation: `{source}` validated against the enum; `limit` bounded.
- Subprocess calls use argument lists (no shell).

## Operations & Deployment

- **Start** via `start-stop-daemon` (survives shell exit):
  `start-stop-daemon --background --make-pidfile --pidfile /tmp/dashboard.pid
  --chdir <dir> --start --exec /tmp/venv/bin/python3 -- -m uvicorn
  backend.app:app --host 0.0.0.0 --port 8000`
- **Python venv**: `/tmp/venv/bin/python3`.
- **Graceful shutdown**: SIGTERM stops the poller thread (finishing any
  in-flight cycle), then uvicorn.
- **Backup**: under WAL, copy with `sqlite3 agy_quota.db ".backup backup.db"`.
- **DB unreadable on boot**: log a clear error and exit non-zero (operator
  removes/recreates the file). No silent reinitialization.

## Testing & Verification Strategy

Two layers, each runnable independently:

1. **Unit tests** (`unittest`, stdlib) in `backend/tests/` — pure functions,
   parser fixtures, and `db.py` round-trips against a temp SQLite file. Fast,
   no network. Parser fixtures live in `backend/tests/fixtures/`.
2. **`verify.py`** — end-to-end verifier covering server health, HTML
   structure, JS functions, CSS rules, all API endpoints, accessibility, and
   regressions (XSS escaping, cache clearing on tab switch, data-relative date
   parsing, 640px layout, stale/offline states, per-source error isolation).
   Grouped so a failing group names the area:

   ```
   verify.py --group server|html|js|css|api|a11y|regression
   ```

   The `a11y` group computes the contrast ratio of the defined color tokens so
   AA compliance is checked, not just asserted. Default run executes all
   groups. Keep and extend the existing 146 checks to cover the new
   robustness/UX/a11y items.

### Commands

```bash
PYTHONPATH=backend python3 -m unittest discover -s backend/tests   # unit
PYTHONPATH=backend python3 verify.py                               # full E2E
PYTHONPATH=backend python3 verify.py --group api                   # one group
```

## Build Order & Milestones (for Agents)

Nine milestones. Complete one, run its verification, then proceed. A milestone
depends only on the *contracts* of earlier modules.

| # | Milestone | Modules | Acceptance Criteria | Verify |
|---|---|---|---|---|
| **M1** | Config + DB | `config.py`, `db.py` | Env overrides; invalid value fails fast; JSON logs; schema idempotent; pragmas applied; insert/read round-trips; prune removes only old rows | `unittest discover` (config, db) |
| **M2** | Parsers | `parsers/base.py`, `opencode.py`, `agy.py`, `codex.py` | Each parses its fixture to the expected tuple; missing files/commands raise `SourceUnavailable` (no crash) | `unittest` parser tests |
| **M3** | Quota enrichment | `quota.py` | Mock RPC → snapshot; timeout → `None`; no secrets in output | `unittest` quota test |
| **M4** | Poller | `poller.py` | One failing source doesn't block others; statuses recorded; prune called each cycle; clean stop | `unittest` poller test |
| **M5** | API | `api.py` | `/health` 200; `/ready` 503 before first poll then 200; usage combined/per-source/history; `?deltas=true`; quota live + `stale` fallback; error envelope + codes | `unittest` api tests + `verify.py --group api server` |
| **M6** | Entry point | `main.py` | Boots, starts poller thread, serves static, `/health` 200, clean SIGTERM | smoke test |
| **M7** | Frontend shell + layout | `index.html`, `styles.css`, `app.js` | Header/tabs/overview/quota/charts render; tab switch clears caches; range & mode recompute without fetch; data-relative time range | `verify.py --group html css js` |
| **M8** | UX states + responsive + a11y | `styles.css`, `app.js` | Loading/error/empty/stale/offline states; 640px layout; ≥44px targets; ARIA + keyboard; reduced-motion; AA contrast | `verify.py --group a11y regression` |
| **M9** | Hardening + full verify | CSP, local-bind, `/metrics`, retention | CSP header present; `/metrics` fields; retention bounds DB; no secrets logged; all groups green; README updated | `verify.py` (all) |

**Dependency rule**: consume earlier modules only through their stated
contracts. If a contract is insufficient, update it in this doc first so
downstream agents stay aligned.

## Key Design Decisions

1. **Per-source isolation with health tracking** — each source is parsed in its
   own `try/except`; failures are recorded in `collection_status`, never
   propagated. A failing source never halts the loop. This is the core of
   robustness for long unattended runs.
2. **Sequential, no backoff** — three sources every ten minutes need neither
   parallelism nor backoff. Sequential polling is simpler and easier to verify;
   the interval is the rate limiter.
3. **No network calls for usage** — AGY/Codex usage comes from local SQLite;
   OpenCode from a subprocess. Only quota enrichment touches the network, with
   timeouts and a snapshot fallback. Works offline.
4. **Poll-driven with DB cache** — the 10-minute poll amortizes I/O and gives
   time-series history even when sources are briefly unavailable; the frontend
   polls the API every 60s.
5. **Quota live enrichment with fallback** — quota endpoints re-fetch live plan
   data but fall back to the last snapshot (marked `stale`) on failure, so the
   user always sees something usable.
6. **Model deltas computed server-side** — Rate mode returns positive
   `current − previous` per model; the frontend switches between `models`
   (Total) and `model_deltas` (Rate).
7. **Time range relative to data** — filtering uses the data's own latest
   timestamp, not `Date.now()`, preventing empty charts from clock skew or
   paused collection.
8. **Client-side filtering** — history is cached after one fetch; range and
   mode changes recompute locally without extra API calls.
9. **Lightweight by construction** — stdlib + FastAPI + uvicorn, Chart.js
   vendored. No ORM, no migrations framework, no frontend framework. Single
   process, single SQLite file with idempotent schema and per-cycle pruning.
10. **Uniform parser contract** — the `(overview, cost_tokens, models)` tuple
    plus `SourceUnavailable` is the single seam for adding sources.
11. **Verification-first** — every backend module has a unit test; every
    frontend concern maps to a named `verify.py` group, so an agent can
    implement, verify, and stop with confidence at each milestone.
12. **UX and accessibility are requirements** — loading/error/empty/stale/
    offline states, keyboard nav, ARIA, AA contrast (contrast computed in
    verify), reduced motion, and ≥44px touch targets are acceptance criteria.
