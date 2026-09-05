# AI Usage Dashboard — Design Document

## Goal

Track token usage, session stats, and quota limits across four LLM coding
agents — **Antigravity (AGY CLI/IDE)**, **Claude (Claude Code)**, **OpenCode
CLI**, and **Codex CLI (OpenAI)** — and surface them in a single, real-time
dashboard that works well on desktop and mobile.

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
| **AGY** | Conversation protobuf blobs from `~/.gemini/antigravity-*/conversations/*.db` | Cloud Code API via local RPC (`RetrieveUserQuotaSummary`) + `loadCodeAssist` for plan (`paidTier.name`). The RPC endpoint belongs to Antigravity itself, so it exists only while the app is running: the language server is located by verifying a candidate process's executable and then taking only its **listening loopback** sockets. No port is ever guessed — an unidentifiable endpoint is reported as `not_running`/`rpc_port_unavailable` rather than probed for. Usage collection is unaffected, since it reads files. |
| **Claude (Claude Code)** | Local `~/.claude/projects/**/*.jsonl` transcripts | Anthropic OAuth usage API (`~/.claude/.credentials.json`) |
| **OpenCode** | `opencode stats --models` subprocess output | Same subprocess; total cost extracted |
| **Codex (OpenAI)** | `~/.codex/state_5.sqlite` threads table | JWT plan (`chatgpt_plan_type`) + a short-lived local `codex app-server --stdio` JSON-RPC session (`account/rateLimits/read`); `logs_2.sqlite` scraping survives only as a deprecated fallback for older Codex releases |

Every source is **optional and isolated**: if a source's files/commands are
absent or fail, the rest of the system keeps working and reports that source
as unavailable rather than crashing.

The Codex App Server protocol is documented by the installed binary itself,
not an external reference: `codex app-server generate-json-schema --out
<dir>` regenerates it, version-matched to whatever CLI is on the host.

#### API Endpoints

| Endpoint | Method | Returns | Notes |
|---|---|---|---|
| `/api/sources` | GET | List of available data sources | Returns `[{name, display_name}]` from source registry |
| `/api/usage/latest` | GET | Latest usage for every source, keyed by source name | Not summed server-side — one raw row per source, same shape as the per-source endpoint; `?deltas=true` adds model deltas; additive `_meta` block carries `{poll_interval_s, latest_cycle_ts, next_cycle_ts}` for the cycle strip |
| `/api/usage/history` | GET | Combined history across all sources | Server-aggregated per `cycle_ts` (`SUM … GROUP BY`); exists and is exercised by tests, but the frontend's "All" tab does not call it — see *Frontend State Machine* |
| `/api/usage/{source}/latest` | GET | Per-source usage (`agy`/`claude`/`opencode`/`codex`) | 404 on unknown source |
| `/api/usage/{source}/history` | GET | Per-source history series | optional `?range=` cap |
| `/api/quota/latest` | GET | Combined quota with plan labels | Served from DB snapshots by default; `?force=true` triggers live refresh |
| `/api/quota/{source}/latest` | GET | Per-source quota | 404 on unknown source; DB snapshot by default |
| `/health` | GET | Liveness — `{ "status": "ok" }`, always 200 if running | — |
| `/ready` | GET | Readiness — 200 once DB is reachable and ≥1 poll succeeded; else 503 | — |
| `/metrics` | GET | Operational metrics (JSON) | per-source last success/error, poll count, DB size |

Data endpoints return the resource directly on success and a uniform error
envelope otherwise (see *API Specification*).

#### Frontend Layout

- **Header**: Title "Model Usage Dashboard" + time range buttons + Live pill in one row. No subtitle.
- **Tabs**: All, AGY, Claude, OpenCode, Codex. Tab label is "All", not "Combined (All)".
- **Overview + Quota**: Side-by-side in `.stats-row` flex container.
- **Overview Cards**: 2×2 grid. Row 1: Sessions/Messages (same row, same size, `/` separator) | Cache Reads. Row 2: Input Tokens | Output Tokens.
- **History Chart**: Stacked area (Total mode) or individual lines (Rate mode).
- **Model Distribution**: Donut chart. Title adapts to mode.
- **Mode Toggle**: Total/Rate. Affects history chart + model chart + overview cards.
- **Time Range**: 1h/6h/1d/1w/1m/3m/all. Affects entire page. Relative to data's latest `cycle_ts`, not `Date.now()`.
- **Model Details Panel**: Shows per-model token/session breakdown for the selected time range. When range is "all", shows cumulative totals from latest snapshot. When a specific range is selected, computes deltas between the earliest and latest history entries in that range.

#### Quota Display

- **AGY**: Model groups with limit bars (`Session 5h` top, `Weekly` bottom). Plan badge dynamic from API (`paidTier.name`).
- **Claude**: Model groups with limit bars (`Session 5h` top, `Weekly` bottom). Plan badge dynamic.
- **OpenCode**: Total cost display.
- **Codex**: One bar per reported window (a primary window, an optional secondary
  window, and any additional metered `limitId`s), each labelled from its own window
  duration — a free-plan primary window happens to be 30 days, but the collector makes
  no monthly assumption. Plan badge only, no cost display. Plan from JWT
  (`chatgpt_plan_type`).

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
│     ├── cycle_ts = floor(now, interval) — shared by all     │
│     ├── quota.py (live enrichment, fallback to snapshot)    │
│     └── writes usage + status; prunes old rows              │
│                       ▼                                     │
│        db.py → usage.db (WAL, idempotent schema)            │
│     usage_history · model_usage · quota_snapshots ·         │
│     quota_plans ·                                           │
│     collection_status · meta  (all keyed by cycle_ts)       │
│                       ▲                                     │
│   api.py (FastAPI: aggregates across sources by cycle_ts)   │
│              /health · /ready · /metrics                    │
├───────────────────────┼────────────────────────────────────┤
│                       ▼                                     │
│   Frontend: index.html + styles.css + app.js + Chart.js     │
│   refresh() every 60s; loading/error/empty/stale states     │
└────────────────────────────────────────────────────────────┘
```

### Data Flow

1. `poller.py` wakes every 600s (configurable). It computes
   `cycle_ts = floor(now, poll_interval)` — the single timestamp all sources
   in this cycle share.
2. For each source **sequentially**, run its parser inside a `try/except`.
   Subprocess/network steps have timeouts; local SQLite reads rely on
   `busy_timeout`. On success, write usage rows keyed by `(source, cycle_ts)`;
   on failure, write only a `collection_status` row. `INSERT OR REPLACE` makes
   each bucket idempotent. One source never aborts the cycle.
3. `quota.py` performs live enrichment (AGY plan, Codex rate limits) with its
   own timeouts; on failure the API serves the last snapshot marked `stale`.
4. `db.py` prunes rows older than the retention window once per cycle.
5. `api.py` reads from the DB. `/api/usage/history` (no source) aggregates
   across sources at each `cycle_ts` (`SUM … GROUP BY cycle_ts`); per-source
   endpoints, and `/api/usage/latest` (no source), return raw per-source rows
   without summing. Quota endpoints re-run live enrichment with snapshot
   fallback.
6. The frontend's "All" tab fetches every source's `latest`/`history` in
   parallel (driven by the source registry, not hardcoded names) and sums
   them client-side — see *Frontend State Machine*. It fetches on load and
   every 60s, recomputes locally on
   range/mode changes (no extra API calls), and shows loading/error/empty/
   stale states.

## Backend Module Breakdown

Ten cohesive modules. Each has one responsibility, an explicit contract, and a
unit test. A module may consume earlier ones only through the stated contract.

| Module | Responsibility | Contract (signatures) | Verify (unit) |
|---|---|---|---|
| `config.py` | Load + validate config from env; configure JSON logging | `load_config() -> Config`; `setup_logging(level)` | Defaults, env override, invalid value rejected; log line is valid JSON |
| `db.py` | Connection + pragmas + idempotent schema + CRUD + aggregation + prune | `connect(path)`, `init_schema(conn)`, `insert_usage(conn, source, cycle_ts, overview, models)`, `latest_usage(conn, source?, cycle_ts)`, `history(conn, source?, range)`, `insert_quota(conn, source, cycle_ts, rows)`, `latest_quota(conn, source)`, `record_status(conn, source, cycle_ts, ok, err, ms)`, `metrics(conn)`, `prune(conn, days)` | Schema idempotent; pragmas applied; `UNIQUE(source, cycle_ts)` enforced; insert/read round-trips; `latest_usage(None, ts)` aggregates across sources; prune removes only old rows |
| `parsers/base.py` | Parser contract + shared types/helpers | `Parser.parse(cfg) -> (overview, cost_tokens, models)`; raises `SourceUnavailable` | Contract shape; helper unit tests |
| `parsers/opencode.py` | OpenCode usage parser (subprocess) | implements `Parser` | Fixture stdout → expected tuple; missing binary → `SourceUnavailable` |
| `parsers/agy.py` | AGY usage parser (local DB / protobuf bytes) | implements `Parser` | Fixture DB → expected tuple; missing files → `SourceUnavailable` |
| `parsers/codex.py` | Codex usage parser (local DB) | implements `Parser` | Fixture DB → expected tuple; missing files → `SourceUnavailable` |
| `quota.py` | Live quota enrichment + fallback | `collect(source, cfg) -> QuotaSnapshot \| None` | Mock RPC → snapshot; timeout → None (caller falls back) |
| `poller.py` | One poll cycle + loop + thread lifecycle | `run_once(cfg, conn)`, `start(cfg)`, `stop()` | Computes shared `cycle_ts`; one failing source doesn't block others; statuses recorded with `cycle_ts`; prune called |
| `api.py` | FastAPI app: routes, error handlers, response schemas, static mount | `create_app(cfg) -> FastAPI` | Routes return correct shapes/codes; `/api/usage/latest` + `/api/usage/history` aggregate across sources by `cycle_ts`; `/ready` 503 before first poll, 200 after; error envelope; static served |
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

Single SQLite file (`backend/usage.db`). Pragmas set in `db.connect()`:
`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
`busy_timeout=5000`. Schema created idempotently with `CREATE TABLE IF NOT
EXISTS`; a one-row `meta(schema_version)` table records the version. Changes
are additive; a breaking change bumps the version and is documented as a
manual step (no migration runner).

**Cycle timestamps** — at the start of each poll cycle the poller computes
`cycle_ts = floor(now, poll_interval)`. Every source read in that cycle
shares this one `cycle_ts`. This aligns data across sources so the "All" view
is a trivial `SUM … GROUP BY cycle_ts` with no client-side alignment. A
`UNIQUE(source, cycle_ts)` constraint on each table makes each bucket
idempotent — a re-run of the same cycle replaces, not duplicates.

- **usage_history**: one row per source per cycle. PK `(source, cycle_ts)`.
  `source`, `cycle_ts`, `sessions`, `messages`, `input_tokens`,
  `output_tokens`, `cache_read`, `cache_write`. Index `(cycle_ts)`.
- **model_usage**: one row per model per source per cycle. `source`,
  `cycle_ts`, `model_name`, `messages`, `input_tokens`, `output_tokens`,
  `cache_read`, `cache_write`, `cost`. Unique `(source, cycle_ts, model_name)`.
- **quota_snapshots**: one row per model group per limit type per cycle.
  `source`, `cycle_ts`, `model_group`, `limit_type`, `used`, `total`,
  `remaining_pct`, `refreshes_in_seconds`, plus (schema v6) `reset_at`,
  `window_minutes`, `limit_label`. `refreshes_in_seconds` is a duration
  captured at write time, so it is already wrong by the time it is read back;
  `reset_at` is the absolute Unix-seconds timestamp the UI counts down from
  instead. `window_minutes`/`limit_label` identify which bucket a row
  describes, which matters once a source (Codex) reports more than one
  window. Unique `(source, cycle_ts, model_group, limit_type)`.
- **quota_plans** (schema v5): the plan/tier a source reports, one row per
  cycle. `source`, `cycle_ts`, `timestamp`, `plan`. Unique `(source, cycle_ts)`.
  It is a scalar, so it cannot live in `quota_snapshots`' model_group/limit_type
  grid; before v5 nothing stored it and every plan badge silently fell back to a
  hardcoded default. `latest_quota()` returns it as `_plan`, taking the most
  recent plan at or before the cycle being read.
- **collection_status**: per-source health per cycle. `source`, `cycle_ts`,
  `ok`, `error` (nullable), `duration_ms`. Unique `(source, cycle_ts)`. Drives
  `/ready`, `/metrics`, and the frontend's per-source availability indicator.
- **meta**: `schema_version` and other small key/values.

**Retention**: `db.prune(conn, retention_days)` runs once per poll cycle (a
cheap `DELETE WHERE cycle_ts < now - retention`) to bound DB growth.

## Poll Loop & Error Handling

- **Shared cycle timestamp**: the poller computes `cycle_ts` once at the start
  of each cycle and passes it to every source read. All rows written in that
  cycle — usage, models, quota snapshots, status — share this `cycle_ts`.
- **Per-source isolation**: each parser/collector call is wrapped in its own
  `try/except`. A failure writes a `collection_status` row and never aborts
  the cycle.
- **Timeouts where hangs happen**: subprocess calls (`opencode stats`) use
  `subprocess.run(timeout=…)`; network calls (quota RPC) use a request
  timeout; the Codex App Server session (`codex app-server --stdio`) uses a
  single wall-clock deadline covering spawn, initialize, and the quota read
  together (`USAGE_NETWORK_TIMEOUT`). Local SQLite reads rely on
  `busy_timeout`. No artificial timeout wrappers around plain file reads.
- **No backoff state**: the 10-minute interval is the rate limiter. A failing
  source is simply retried next cycle.
- **Partial writes**: each source's usage rows are written in their own
  transaction; a failed source writes only a status row.
- **Quota fallback**: `api.py`'s `_get_cached_quota`/`_annotate` helpers attach a
  per-source `_status` envelope (`live`, `observed_at`, `age_seconds`, `stale`,
  and `error_category` when a read failed) to every quota response. A failed
  read is never cached as a success, and a forced (`?force=true`) refresh that
  fails returns the last persisted `quota_snapshots` row marked `stale: true`
  instead of an empty object — a live source never blanks out in front of the
  user.
- **Lifecycle**: the poller runs in a background thread with a
  `threading.Event` so `main.py` stops it cleanly on SIGTERM.
- **Data Integrity Monitor**: If a source fails to report during a cycle, a Data Integrity Monitor carries forward the preceding valid record for that source (along with its model usage and quota snapshots), keeping the time-series contiguous.
- **In-Memory Server State Warning**: Since the poller runs as a background thread inside the FastAPI/uvicorn server process, code modifications to the poller loop or database schema require a complete process restart to flush the in-memory state. Failing to restart will result in the old poller code continuing to write data (often corrupting values or recording 0s). Any corrupted intervals should be deleted from `usage_history`, and the Data Integrity Monitor should be run retrospectively to backfill them.

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
| `USAGE_DB_PATH` | `backend/usage.db` | SQLite location |
| `USAGE_POLL_INTERVAL` | `600` | Seconds between polls |
| `USAGE_SUBPROCESS_TIMEOUT` | `20` | Timeout for CLI subprocess calls |
| `USAGE_NETWORK_TIMEOUT` | `10` | Timeout for quota/network calls; also bounds the whole Codex App Server session (spawn, initialize, and the quota read together) |
| `USAGE_RETENTION_DAYS` | `90` | History pruning window |
| `USAGE_HOST` | `127.0.0.1` | Bind host — loopback-only by default; there is still no auth on any route (see Security below), so widen this deliberately, e.g. `USAGE_HOST=0.0.0.0` for LAN/tailnet reach |
| `USAGE_PORT` | `8000` | Bind port |
| `USAGE_LOG_LEVEL` | `INFO` | Logging level |
| `USAGE_CODEX_BIN` | `codex` | Codex CLI for `codex app-server --stdio` quota reads. A bare name resolves on `PATH`, then `~/.local/bin/codex` and `/usr/local/bin/codex`; a path is used as given. Must be set explicitly under systemd — see `install/usage-dashboard.default`. |
| `USAGE_FORCE_MIN_INTERVAL` | `10` | Minimum seconds between live quota collections for one source, however many `?force=true` refreshes arrive. Forced refresh bypasses the read cache, so it is the only route that spawns a subprocess and calls an upstream API on demand; the floor keeps that bounded. Attempts are counted, not just successes, so a failing source cannot be hammered either. |

Invalid values fail fast on load with a clear message.

## Frontend Design Identity

Recorded here because the reasoning is not recoverable from the CSS: the tokens
say *what* the colours are, not *why*.

The page is a **meter for metered resources** — tokens in, tokens out, cost
accruing, quotas draining. Its closest relatives are the utility smart-meter and
the mission-control telemetry console, not a SaaS marketing dashboard. Every
visual decision follows from that:

- **Direction: warm graphite telemetry console with phosphor-amber signalling.**
  The look it replaced was near-black navy with blue/purple glassmorphism and a
  gradient headline — the generic "AI SaaS dark dashboard", which could have
  been any product.
- **Why this isn't just another dark-plus-accent default.** The base is a *warm
  neutral* graphite with no blue cast; the accent is amber rather than
  acid-green or vermilion; the per-source hues are semantically required, since
  each agent keeps its own identity colour; and the personality is carried by
  the mono data typography and meter-hardware motifs rather than by the accent.
- **Typography as instrument readout.** IBM Plex Mono with `tabular-nums` for
  every number on the page (KPIs, table cells, axis ticks, quota readouts, the
  countdown); IBM Plex Sans for UI prose; the wordmark is a letterspaced mono
  console label, not a marketing headline. Fluid `clamp()` scale, so type never
  jumps at a breakpoint.
- **Quota as physical meter.** Segmented ticks with a `--danger` tail past 90%,
  rather than a generic rounded progress bar.
- **Motion is one orchestrated moment**, not scattered effects: the cycle-strip
  sweep, collapsing to a static countdown under `prefers-reduced-motion`. Card
  hover brightens the border only — no translate lift. A source-switch View
  Transition was considered and deliberately dropped (see the commit retiring
  the UI uplift plan): tab switching already repaints from cached state inside a
  frame budget.

Chart.js reads its colours from these tokens once via `getComputedStyle` at
init and passes them into `Chart.defaults`, so charts and UI cannot drift apart.

## Frontend Architecture

**Modular ES6 architecture** loaded as native modules (no build step):
`<script type="module" src="js/main.js">`. Splitting the old monolithic `app.js`
into focused modules improves maintainability and testability. `verify.py`
checks for the presence of expected functions and CSS rules across the
distributed files.

**Core modules:**

| Module | Responsibility | Exports |
|---|---|---|
| `state.js` | Single mutable state object + configuration constants | `state`, constants |
| `api.js` | All network fetches, envelope parsing, offline detection | `fetchJSON(path)`, `fetchUsageLatest()`, `fetchUsageHistory()`, etc. |
| `format.js` | Pure string formatters (no side effects) | `formatNumber()`, `formatTime()`, `formatPercent()`, etc. |
| `colors.js` | Read design tokens from CSS custom properties; build color maps | `getColorValue(token)`, `getSourceColors()` |
| `charts.js` | Chart.js configuration objects for history and distribution | `historyChartConfig()`, `distributionChartConfig()` |
| `derive.js` | Read-time aggregations from history: totals, deltas, time-bucketed sums | `deriveOverview()`, `deriveModelDeltas()` |
| `ui/*.js` | Component renderers (banners, skeleton, KPIs, table, quota meters, cycle strip) | `renderBanners()`, `renderSkeleton()`, `renderKpis()`, `renderTable()`, `renderQuota()`, `renderCycleStrip()` |
| `main.js` | Bootstrap: wire state → render → refresh loop; event delegation | `init()`, `refresh()` |

**Design system** (CSS):

`index.css` is organized in layers (`@layer`) for predictable cascade:
- **Reset**: normalize.css-like baseline across browsers.
- **Tokens**: CSS custom properties for color, spacing, typography, z-index, transitions.
  Color palette is dark-only warm graphite with phosphor-amber signal. IBM Plex Sans for UI,
  IBM Plex Mono (tabular figures) for all numerals. All colors are colourblind-validated (worst ΔE >9 under simulated protanopia; AA contrast ≥3:1).
- **Base**: element defaults (headings, buttons, inputs).
- **Components**: layout & composition blocks (`.header`, `.tabs`, `.stats-row`, `.card`, `.chart-container`).
- **Utilities**: one-off rules (`.hidden`, `.truncate`, responsive helpers).

**Responsive strategy**:
- Container queries + two viewport breakpoints (1024px, 640px) replace five breakpoints.
- Mobile layouts: stacked header, scrollable tabs, single-column stats, cards replace table rows.
- Touch targets ≥44×44px; reduced padding on mobile.
- No layout shift: skeleton placeholders match final size.

### Frontend State Machine

Three independent state variables; changing one triggers a targeted recompute:

```
source (tab)      → invalidates caches, full refresh (combined or per-source)
range (1h/6h/…)   → filters cached history, recomputes overview (no fetch)
mode (total/rate) → toggles chart stack↔line + uses model_deltas (no fetch)
```

The "All" tab does not call the combined `/api/usage/history` endpoint. It
fetches `/api/usage/{source}/history` and `/api/usage/{source}/latest` for
every registered source in parallel (source names come from the registry via
`getSourceNames()`, not a hardcoded list) and sums/merges them client-side —
aligning history on the latest timestamp every source has reported, so a
lagging source can't understate the total. Per-source tabs fetch the same
`{source}/history` and `{source}/latest` endpoints directly, unsummed.
`cachedHistory` and `cachedLatestOverview` are cleared on tab switch. Range
and mode changes recompute locally from cached data without extra API calls.

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
- **No authentication, bound to `127.0.0.1` by default** — there is nothing
  route-specific gating access; anyone who can reach the bound host and port
  can read usage/quota data and `/metrics`. The loopback-only default means
  nothing off the host can reach it out of the box. Widen this deliberately
  only if you have a reason to: set `USAGE_HOST=0.0.0.0` (or a specific LAN
  address) to make it LAN/tailnet-reachable, and put it behind a reverse
  proxy with auth, or an SSH tunnel / `tailscale serve`, if the network isn't
  fully trusted.

## Publishing to GitHub

This project lives only here, as a subdirectory of the `main` monorepo (Gitea
`origin` remote). There is no separate on-disk copy for the public GitHub
release anymore — `~/workspace/ai-usage-dashboard-standalone` was retired on
2026-07-04 (it had drifted from this copy and needed manual syncing) and later
deleted outright once its leaked PAT was revoked and nothing else in it was
worth keeping.

**Don't use `git subtree split` for this** — it carries this subdirectory's
*full* monorepo history along with it, and that history isn't safe to publish:
it contains `IMPROVE.md` (references the internal Gitea address and other
internal-only tracking docs) and, in an old commit, a real `usage.db.bak` with
actual personal usage data that was later deleted but is still reachable via
history. A 2026-07-04 audit confirmed no other secrets exist in this
subdirectory's history, but those two are enough to rule out any
history-preserving publish method.

Instead, publish as a **fresh, single-commit snapshot** of the current tree,
with internal-only files stripped, and push over SSH (`git@github.com`, key at
`~/.ssh/keys/github_omv`, registered on the `chrischanson` GitHub account):

```bash
SNAP=$(mktemp -d)
cd ~/workspace/main
git archive HEAD public_projects/ai-usage-dashboard | tar -x -C "$SNAP" --strip-components=2
rm "$SNAP/IMPROVE.md"   # internal-only — never publish this file
cd "$SNAP"
git init -q -b main && git add -A && git commit -q -m "Sync from internal monorepo: <summary>"
git remote add github git@github.com:chrischanson/ai-usage-dashboard.git
git push --force github main:main   # replaces prior history — expected every time
```

This is a one-way door for a public repo each time (replaces history other
clones have), so re-run the secrets/internal-reference scan on `$SNAP` before
pushing if anything beyond routine code changes has landed since the last
release.

## Operations & Deployment

- **Start** via `start-stop-daemon` (survives shell exit):
  `start-stop-daemon --background --make-pidfile --pidfile /tmp/dashboard.pid
  --chdir <dir> --start --exec /tmp/venv/bin/python3 -- -m uvicorn
  backend.app:app --host 0.0.0.0 --port 8000`
- **Python venv**: `/tmp/venv/bin/python3`.
- **Graceful shutdown**: SIGTERM stops the poller thread (finishing any
  in-flight cycle), then uvicorn.
- **Backup**: under WAL, copy with `sqlite3 usage.db ".backup backup.db"`.
- **DB unreadable on boot**: log a clear error and exit non-zero (operator
  removes/recreates the file). No silent reinitialization.

## Testing & Verification Strategy

Two layers, each runnable independently:

1. **Unit tests** (`pytest`) in `backend/tests/` — pure functions, parser
   fixtures, and `db.py` round-trips against a temp SQLite file. Fast, no
   network. Parser fixtures live in `backend/tests/fixtures/`. Install the
   `dev` extra (`pip install -e '.[dev]'`, or `pip install -r
   requirements-dev.txt`) to get `pytest` alongside the pinned runtime deps.
   311 tests (plus subtests) as of this writing; CI runs this exact suite.
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
   groups: 328 checks as of this writing.

A real Codex App Server query (spawning `codex app-server --stdio` against an
installed CLI and reading a live account's rate limits) is a manual smoke
test only. Neither layer above depends on it — CI mocks Codex, and no test
requires a real ChatGPT/Codex account.

### Commands

```bash
PYTHONPATH=backend python3 -m pytest -q backend/tests   # unit
PYTHONPATH=backend python3 verify.py                    # full E2E
PYTHONPATH=backend python3 verify.py --group api        # one group
```

## Build Order & Milestones (for Agents)

Nine milestones. Complete one, run its verification, then proceed. A milestone
depends only on the *contracts* of earlier modules.

| # | Milestone | Modules | Acceptance Criteria | Verify |
|---|---|---|---|---|
> The **Verification** column below records the tooling each milestone was
> built and accepted against. The suite has since moved to `pytest` (several
> test modules use pytest-style classes that `unittest discover` cannot
> collect), so treat that column as history, not as the command to run today —
> see *Testing & Verification Strategy* above for the current one.

| **M1** | Config + DB | `config.py`, `db.py` | Env overrides; invalid value fails fast; JSON logs; schema idempotent; pragmas applied; `UNIQUE(source, cycle_ts)` enforced; insert/read round-trips; `latest_usage(None, ts)` aggregates across sources; prune removes only old rows | `unittest discover` (config, db) |
| **M2** | Parsers | `parsers/base.py`, `opencode.py`, `agy.py`, `codex.py` | Each parses its fixture to the expected tuple; missing files/commands raise `SourceUnavailable` (no crash) | `unittest` parser tests |
| **M3** | Quota enrichment | `quota.py` | Mock RPC → snapshot; timeout → `None`; no secrets in output | `unittest` quota test |
| **M4** | Poller | `poller.py` | One failing source doesn't block others; statuses recorded; prune called each cycle; clean stop | `unittest` poller test |
| **M5** | API | `api.py` | `/health` 200; `/ready` 503 before first poll then 200; `/api/usage/latest` + `/api/usage/history` server-aggregated by `cycle_ts`; per-source latest/history; `?deltas=true`; quota live + `stale` fallback; error envelope + codes | `unittest` api tests + `verify.py --group api server` |
| **M6** | Entry point | `main.py` | Boots, starts poller thread, serves static, `/health` 200, clean SIGTERM | smoke test |
| **M7** | Frontend shell + layout | `index.html`, `styles.css`, `app.js` | Header/tabs/overview/quota/charts render; "All" tab fetches combined endpoints (no client-side aggregation); tab switch clears caches; range & mode recompute without fetch; data-relative time range | `verify.py --group html css js` |
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
   `cycle_ts`, not `Date.now()`, preventing empty charts from clock skew or
   paused collection.
8. **Shared cycle timestamp** — all sources in a poll cycle share one
   `cycle_ts` (interval-floored), so every source's rows for a cycle land on
   the same bucket with no client-side timestamp alignment needed. `db.py`
   also exposes a server-aggregated `/api/usage/history` (`SUM … GROUP BY
   cycle_ts`), but the "All" tab does not currently use it — see *Frontend
   State Machine* for what it actually fetches and how it combines sources.
9. **Client-side range/mode filtering** — history is cached after one fetch;
   range and mode changes recompute locally without extra API calls.
10. **Lightweight by construction** — stdlib + FastAPI + uvicorn, Chart.js
    vendored. No ORM, no migrations framework, no frontend framework. Single
    process, single SQLite file with idempotent schema and per-cycle pruning.
11. **Uniform parser contract** — the `(overview, cost_tokens, models)` tuple
    plus `SourceUnavailable` is the single seam for adding sources.
12. **Verification-first** — every backend module has a unit test; every
    frontend concern maps to a named `verify.py` group, so an agent can
    implement, verify, and stop with confidence at each milestone.
13. **UX and accessibility are requirements** — loading/error/empty/stale/
    offline states, keyboard nav, ARIA, AA contrast (contrast computed in
    verify), reduced motion, and ≥44px touch targets are acceptance criteria.

# Future Roadmap & Improvement Plan

## Improvement Plan — Claude Support + Robustness

Status: **proposal** (no code written yet). Date: 2026-07-02.

Two goals: (1) add **Claude (Claude Code)** as a fourth source, including
5-hour-session and weekly limit remaining; (2) make the system **more
robust**. Feasibility of (1) was verified live on this machine — see below.

---

### Part 1 — Claude source

#### 1.1 Verified data sources (tested 2026-07-02 on this host)

**Quota (5h + weekly): OAuth usage endpoint.** This is the same endpoint
Claude Code's `/usage` panel uses.

- Token: `~/.claude/.credentials.json` → `claudeAiOauth.accessToken`
  (plus `subscriptionType` — e.g. `"pro"` — for the plan badge, and
  `expiresAt` in **milliseconds**).
- Request: `GET https://api.anthropic.com/api/oauth/usage` with headers
  `Authorization: Bearer <accessToken>` and `anthropic-beta: oauth-2025-04-20`.
- Verified response (HTTP 200) contains exactly what we need:

```json
{
  "five_hour": { "utilization": 10.0, "resets_at": "2026-07-03T07:20:00+00:00" },
  "seven_day": { "utilization": 2.0,  "resets_at": "2026-07-08T10:00:00+00:00" },
  "limits": [
    { "kind": "session",       "group": "session", "percent": 10, "severity": "normal", "resets_at": "...", "is_active": true },
    { "kind": "weekly_all",    "group": "weekly",  "percent": 2,  "severity": "normal", "resets_at": "..." },
    { "kind": "weekly_scoped", "group": "weekly",  "percent": 1,  "scope": { "model": { "display_name": "Fable" } } }
  ]
}
```

`utilization`/`percent` are % used; `remaining = 100 − utilization`.
`limits[]` additionally gives per-model weekly limits and a `severity`
(`normal`/…) we can color bars with. Fields like `used_dollars` are null on
subscription plans — ignore them.

**Usage history: local transcripts.** `~/.claude/projects/**/*.jsonl` —
one file per session. Assistant lines carry
`message.usage = { input_tokens, cache_creation_input_tokens,
cache_read_input_tokens, output_tokens }` and `message.model`. Verified
present on this host. This is local-first, consistent with the design's
"no network calls for usage" rule.

#### 1.2 New modules (mirror the Codex pattern)

**`claude_parser.py`** → returns the standard `(overview, cost_tokens,
models)` / `ParserResult` contract:

- Scan `~/.claude/projects/**/*.jsonl` (path overridable via
  `CLAUDE_HOME`/`USAGE_CLAUDE_DIR` env).
- Sessions = distinct transcript files (or `sessionId`s); messages = user +
  assistant message lines.
- Tokens: sum `message.usage` per `message.model`. **Dedup required**: the
  same assistant message can appear on multiple lines (streaming rewrites,
  resumed sessions) — dedup on (`message.id`, `requestId`) before summing,
  the same approach ccusage uses. Count sidechain (sub-agent) lines too but
  dedup applies equally.
- Map `cache_read_input_tokens` → `cache_read`,
  `cache_creation_input_tokens` → `cache_write`.
- Missing `~/.claude/projects` → `SourceUnavailable` (source shows as
  unavailable, nothing crashes).
- Cost: skip (subscription plan; no reliable local price data). Column stays 0.

**`claude_quota.py`**:

- Read credentials file; if missing (e.g. macOS Keychain-only setups) or
  `expiresAt <= now`, return `{'error': ...}` → API serves last snapshot
  marked stale. **Never refresh the token ourselves** — refreshing rotates
  it and can race/log out Claude Code. Claude Code refreshes it on next use;
  we just re-read the file each poll.
- Call the usage endpoint with `USAGE_NETWORK_TIMEOUT`. On 401/timeout →
  error dict (stale fallback), never raise past the collector.
- Output rows fit the existing `quota_snapshots` schema unchanged:
  - `model_group='session'`, `limit_type='five_hour'`
  - `model_group='weekly'`, `limit_type='all_models'`
  - `model_group='weekly'`, `limit_type='<model display_name>'` for each
    `weekly_scoped` entry
  with `used=utilization`, `total=100`, `remaining_pct=100−utilization`,
  `refreshes_in_seconds = resets_at − now`.
- Plan badge: `subscriptionType` from credentials ("Claude Pro" / "Claude
  Max"), like Codex's JWT-derived badge.
- Security: never log or store the token; only derived percentages go to DB.

#### 1.3 Wiring

- **Poller**: register `claude` usage + quota collectors (one line each once
  the source registry from Part 2 exists).
- **API**: `claude` becomes valid in the per-source routes (free after the
  `{source}` route refactor below; without it, 8 more copy-pasted handlers).
- **Frontend**: add a "Claude" tab; quota card renders two headline bars —
  "Session (5h): X% left, resets in Hh Mm" and "Week: Y% left, resets <day>"
  — plus per-model weekly bars when present, using the existing AGY
  limit-bar renderer. Color by `severity`/threshold (amber ≥ 75% used, red ≥
  90%). Plan badge next to the tab title.
- **Polling cadence**: quota comes from the 10-min poll snapshot, same as
  other sources, with the existing live-enrichment-on-request pattern for
  `/api/quota/claude/latest` **behind a ≥60 s in-process TTL cache** so the
  60 s frontend loop can't hammer Anthropic (see robustness item R7).
- **Docs**: README + DESIGN source tables gain a Claude row.

#### 1.4 Tests

- Fixture JSONL transcript (few sessions, duplicate message.id lines,
  sidechain lines) → expected ParserResult; missing dir → `SourceUnavailable`.
- `claude_quota` with a mocked HTTP response (the verified JSON above) →
  expected snapshot rows; expired-token fixture → stale path; 401 → stale path.
- verify.py: extend `api` group for `/api/usage/claude/*` +
  `/api/quota/claude/latest`, `html/js` groups for the tab and quota card.

---

### Part 2 — Robustness

Findings from reading the code (ordered by impact). Each is a discrete,
independently verifiable change.

> **Audited 2026-09-04. All items are now resolved**, though R4 was resolved by
> a different route than the one proposed below and R7's `?limit=` clause was
> made obsolete by a later revision of the API table above. Each item carries
> its status; the original text is left intact so the reasoning stays readable.

#### R1. Unit tests don't cover the production parse path (highest impact)
`backend/tests/test_parsers.py` tests the `parsers/` package
(`OpenCodeParser`, `AgyParser`, `CodexParser`), but the poller actually
imports the flat modules `parser.py`, `agy_parser.py`, `codex_parser.py`.
Two parallel implementations; the tested one is dead code in production.
**Fix**: pick one home (the `parsers/` package, per DESIGN), port the flat
modules' logic into it, make the poller consume it, delete the duplicates.
The Claude parser then lands in the consolidated location from day one.
**Status: done.** The flat modules are gone; `parsers/` holds `agy`, `claude`,
`codex`, `opencode` and `base`, and both `source_registry` and
`provider_loader` import only from there.

#### R2. `collection_status` collisions hide failures
`record_status` is called twice per source per cycle (usage, then quota)
with the same `(source, cycle_ts)` key and `INSERT OR REPLACE` — the quota
status **overwrites** the usage status. A failed usage parse followed by a
successful quota fetch reports `ok=1`. `/metrics` and `/ready` lie.
**Fix**: add a `kind` column (`usage`/`quota`) to the unique key (or record
quota as `source='<src>:quota'`); surface both in `/metrics`. Also drop the
dual-signature back-compat shim in `record_status`.
**Status: done.** `UNIQUE(source, kind, cycle_ts)`, migrated in schema v2.
`record_status` takes `kind` explicitly and the shim is gone; `metrics()`
groups by `(source, kind)`.

#### R3. Retention is never enforced
`db.prune()` exists, is tested in verify.py, and is **never called** by the
poller — `USAGE_RETENTION_DAYS` does nothing and the DB grows without bound
(DESIGN requires prune once per cycle). **Fix**: call it at the end of
`run_once`. **Status: done.**

#### R4. Integrity monitor can fabricate data indefinitely
`fix_cycle_integrity` carries the last row forward whenever a source misses
a cycle, but (a) carried rows are **indistinguishable** from real readings,
and (b) there's no cap — uninstall Codex and the dashboard shows a healthy
flat line forever, while quota snapshots are duplicated as if fresh.
**Fix**: add a `carried_forward` flag column (surface it in the API so the
frontend can render gaps differently / show the stale badge); cap
carry-forward at N consecutive cycles (e.g. 6 = 1 h), after which the gap is
real and the source shows unavailable. Don't carry quota snapshots forward —
the stale-fallback path already covers quota.
**Status: resolved, by removal rather than by this fix.** Schema v3 made the
poller the only writer and stores raw observations, deriving totals and deltas
at read time, so there is nothing to carry forward and `fix_cycle_integrity`
no longer exists. `integrity.py` is now a *validating* checker
(`check_integrity`) plus attribution reconciliation, which does write
`model_usage` rows — a separate, deliberate mechanism, not cycle fabrication.
No `carried_forward` column was needed.

#### R5. Poller silently drops data and mis-reports success
`_poll_source` only inserts when `sessions or messages` is truthy, but still
records `ok=True` — an all-zero (or shape-mismatched) result looks
successful while writing nothing, which then triggers R4's fabrication.
**Fix**: record a distinct status (`ok=False, error='empty result'`) or
insert the zero row honestly; decide per source and test it.
**Status: done.** `_poll_usage` records `ok=False, error='empty result'`.

#### R6. Live collector calls inside request handlers
`/api/quota/*` handlers call `fetch_agy_quota()` / `fetch_codex_quota()` /
`fetch_opencode_cost()` synchronously on every request. The frontend polls
every 60 s, so network/subprocess work runs 10× more often than the poll
interval that's supposed to be the rate limiter, and the quota-formatting
logic is duplicated between `api.py` and `poller.py`.
**Fix**: one shared "collect + normalize" function per source used by both;
in the API, wrap it in a small in-process TTL cache (≥60 s) and fall back to
the last snapshot with an explicit `stale: true` marker.
**Status: done.** `source_registry` supplies one collector/normalizer pair per
source to both poller and API; `_get_cached_quota` is the 60 s TTL cache with
a per-source stampede lock, and it never caches a failure as a success. The
stale marker is the per-source `_status` envelope (`live`, `observed_at`,
`age_seconds`, `stale`, `error_category`), which every quota card renders.

#### R7. Copy-pasted per-source routes → add a source registry
Eight near-identical handlers for three sources (soon four). Unknown sources
fall through to the generic 404 instead of the specified `source_unknown`
envelope, and `?range=`/`?limit=` from DESIGN are unimplemented.
**Fix**: a `SOURCES` registry (name → parser, quota collector, quota
normalizer) consumed by poller and API; routes become
`/api/usage/{source}/latest|history` with registry validation → 404
`source_unknown`. Adding Claude (or removing a source) becomes a one-line
registry change. Frontend similarly derives tabs from a config array instead
of hardcoded `agy` special cases where practical.
**Status: done.** `source_registry` (and YAML providers via `provider_loader`)
is consumed by both poller and API; unknown sources return the
`source_unknown` envelope; `?range=` is implemented. The frontend injects tabs
from `/api/sources` — only the "All" tab is static markup. The `?limit=`
clause is **obsolete**: the API table above no longer specifies it.

#### R8. Config isn't actually the single source of truth
`db.py` reads `USAGE_DB_PATH` into a module-global `DB_PATH` at import time
and `api.py` uses it directly, bypassing `Config`; several db functions open
their own ad-hoc connections via `connect(DB_PATH)`. Tests that set a temp
DB path can silently hit the real DB.
**Fix**: thread one `Config` through `create_app(cfg)`/db calls; kill the
module-global.
**Status: done.** `db.DB_PATH` is gone, replaced by `default_db_path()` which
resolves at call time for the few callers without a Config.
`create_app(cfg=None, poller=None)` closes over `cfg.db_path`; `cfg` stays
optional so the zero-arg form still works. The freshness tests now inject a
temp-DB Config instead of monkeypatching a global, and both `verify.py` and
`test_app_wiring.py` assert the global stays gone.

#### R9. Operational polish (small, do opportunistically)
- ~~`/ready` and `/metrics` run `init_schema()` on every request~~ — **done**,
  moved into `create_app()` at startup.
- ~~Poller logs with `print()`~~ — **done**. `config.setup_logging()` installs
  `JsonLogFormatter` (one JSON object per line, exception as a single `exc`
  field), poller log calls carry `source`/`cycle_ts`/`duration_ms`/`kind` via
  `extra=`, and `main.py` passes `log_config=None` so uvicorn's own lines go
  through the same formatter instead of printing plain text alongside.
- ~~`main.py` installs SIGTERM handlers that `sys.exit()`~~ — **done**. The
  handlers were in fact dead: uvicorn installs its own during startup, so
  `poller.stop()` never ran. `create_app(cfg, poller=...)` now owns the poller
  in the app lifespan, `main.py` installs no handlers, and both `verify.py`
  and `test_app_wiring.py` assert they are not reintroduced.
- ~~`config.py` error message bug~~ — **done**, uses `', '.join`.
- Repo hygiene — **mostly done**: `usage.db.bak`, `poll_once.py`,
  `seed_test_data.py` and `migrate_db.py` are gone; `dashboard.log` is
  gitignored; README and DESIGN now agree that `USAGE_HOST` defaults to
  `127.0.0.1`. **Not done**: `setup_mock_sources.py` still lives in `backend/`
  rather than a `scripts/` dir — deliberately, since it is not an orphan
  (`.github/workflows/test.yml` invokes it by that path) and moving it would
  churn CI for a cosmetic gain.

---

### Suggested milestone order

| # | Work | Why this order | Verify |
|---|---|---|---|
| M1 | R1 parser consolidation + R7 source registry & `{source}` routes | Everything else (incl. Claude) plugs into this seam | unit tests + `verify.py --group api` |
| M2 | Claude usage parser + tests | Independent of quota; gives the tab data | parser unit tests |
| M3 | Claude quota collector + snapshot mapping + tests | Endpoint verified working; schema needs no change | quota unit tests |
| M4 | Frontend: Claude tab + 5h/weekly quota card | Depends on M2/M3 | `verify.py --group html js css` |
| M5 | R2 status kinds, R3 prune, R5 honest statuses | Data-integrity trio; small independent diffs | unit tests + `/metrics` check |
| M6 | R4 carried_forward flag + cap | Builds on R2/R5 semantics | integrity unit tests |
| M7 | R6 TTL cache + shared normalizers, R8 config threading | API-side cleanup | `verify.py` full |
| M8 | R9 polish + docs (README/DESIGN Claude rows, config table) | Last | `verify.py` full + CI |

Rollback safety: every milestone is additive or behind the existing schema
(one new nullable column in M5/M6: `kind`, `carried_forward` — additive per
the DESIGN migration policy, bump `schema_version`).

### Open questions (defaults chosen, flag if you disagree)

1. **Claude cost column**: leave at 0 (subscription plan) vs. compute from
   public per-token pricing. Default: leave at 0.
2. **Transcript scan cost**: full rescan each 10-min cycle (simple, matches
   AGY) vs. incremental offsets in `meta`. Default: full rescan; revisit if
   a cycle exceeds ~1 s on real data.
3. **Carry-forward cap** (R4): proposed 6 cycles (1 h). Any preference?
