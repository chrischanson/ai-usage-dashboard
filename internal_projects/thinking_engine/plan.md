# Thinking Engine — System Plan v1.2
# Refined against task_schema.md plus real task examples (ebay_deal_hunter, stock_buy_opportunity)

## What It Is

A self-hosted, self-improving agentic pipeline that runs XML-defined tasks on schedule, executes multi-stage LLM pipelines per task, evaluates output quality with a judge LLM, and iteratively improves its own prompts and parameters over time.

---

## Goal Statement

A self-hosted research and signal automation system that monitors multiple domains simultaneously — stock buy opportunities, eBay deals, earnings sentiment, news — and surfaces only high-conviction findings via Pushover notification. Runs unattended, routes compute across free/paid LLM credits, gets measurably better through autonomous prompt evolution.

**Success criteria (6-month):**
1. **Alert precision ≥ 80%** — thumbs up/down feedback drives evolution
2. **≥ 5 hours/week saved** — research tasks run automatically
3. **Cost < $20/month** — free tiers for high-frequency tasks, paid only where quality matters

---

## Task Schema (XML-based)

Tasks are defined as XML files with 10 structured sections. The schema supports:
- **Multi-stage prompts** — stages run sequentially with `depends_on` conditions
- **Per-stage routing** — different LLM per stage based on task requirements
- **Parameterized watchlists** — user-editable config inside the task file
- **Judge LLM evaluation** — a separate cheap model scores every output
- **Child task spawning** — successful runs can trigger child tasks with field passing
- **Selective evolution** — mutation targets specific XML paths, not the whole prompt

See `task_schema.md` for the full annotated schema.

### Real Tasks Defined

| Task ID | Domain | Schedule | Stages | Budget/run |
|---------|--------|----------|--------|------------|
| `stock_buy_opportunity` | trading | 3×/day weekdays | 3 (signals → thesis → risk) | $0.08/ticker |
| `ebay_deal_hunter` | commerce | every 3h | 2 (condition → deal eval) | $0.10/item |
| `earnings_sentiment` | trading | weekdays 8am | 1 | $0.05/run |
| `tech_news_digest` | research | daily 7am | 1 | $0.02/run |

### Planning Verification Summary

The project is well planned at the concept and architecture level: the XML schema has clear task identity, goals, measurement, scheduling, context, execution, evolution, and alerting sections; the two real examples exercise the hardest parts of the engine instead of only toy jobs.

The plan needs a few refinements before implementation:
- Treat XML parsing and validation as a first-class product surface. The examples use nested structures, repeated `<cron>` elements, stage-level routing inside `<execution><routing><stage ref=...>`, conditional expressions, alert formats, and child field passing. A loose parser will make later phases brittle.
- Build fan-out explicitly. Both stock and eBay tasks run per watchlist item, but the scheduler fires the task. The executor needs a `TaskRun` parent plus per-item `WorkItemRun`/stage outputs, or run history, budgets, dedup, and alerts will blur together.
- Separate stage gates from final alert gates. `depends_on` controls whether a stage runs; judge thresholds and task filters control whether the result alerts or spawns children.
- Validate external API capabilities before coding around them. The examples assume specific Polygon, eBay, search, and options-flow capabilities; adapters should expose capability checks and fallback behavior.
- Put feedback and ground-truth loops in the schema and database from the start, even if evolution waits until Phase 4. Otherwise alert precision cannot be measured cleanly.

### Schema Refinements Required

Before implementation, update `task_schema.md` or treat these as accepted extensions:
- Add `commerce` to allowed `task@domain` values because `ebay_deal_hunter` uses it.
- Add `<parameters>` to the element reference; both real examples depend on watchlists, filters, and signal weights.
- Document repeated `<cron>` entries and optional schedule gates such as `<market_hours_only>` and `<skip_if>`.
- Document multi-stage prompts as `<prompt><stage id=... depends_on=...>`, while still allowing the minimal single-stage `<system>/<user>` shape.
- Document execution routing variants: flat `<provider>` list and per-stage `<stage ref=...><provider>...`.
- Document alert options used by examples: `<priority>`, `<dedup_window_hours>`, digest `timezone`, and digest `content`.
- Document child `trigger` values (`on_success`, `on_alert_sent`), `delay_hours`, and field-passing semantics.

---

## Architecture Overview

### Container Stack (3 services)

| Service | Image | Purpose |
|---------|-------|---------|
| `db` | `pgvector/pgvector:pg17` | Task versions, runs, feedback, scheduler state, optional embeddings |
| `engine` | `python:3.12-slim` | FastAPI + APScheduler + task executor |
| `ollama` | `ollama/ollama:latest` | Local LLM fallback (always free) |

### Core Execution Flow

```
Task XML file
    │
    ▼
TaskLoader — parse XML, validate schema, extract stages/parameters
    │
    ▼
Scheduler — APScheduler cron trigger (persisted to PostgreSQL)
    │
    ▼
Executor — create parent run, expand watchlist/listing work items
    │
    ├── For each work item, bounded by max_concurrent:
    │   ├── ContextResolver — fetch typed inputs (API, web_search, results_store, cache)
    │   ├── For each stage:
    │   │   ├── StageGate — check depends_on condition
    │   │   ├── PromptRenderer — inject context variables into stage prompt
    │   │   ├── ProviderRouter — pick cheapest capable provider for THIS stage
    │   │   ├── LLM call via litellm (with retry on parse failure)
    │   │   └── OutputParser — extract JSON, validate expected fields
    │   └── JudgeLLM — score composite output against rubric criteria
    │
    ▼
ResultStore — persist parent run + item outputs + stage outputs + judge scores
    │
    ├── if composite >= alert_above → AlertDispatcher (Pushover)
    ├── if composite < evolve_below → flag for evolution cycle
    └── if children defined + condition met → spawn child tasks
```

---

## Directory Structure

```
thinking-engine/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── init.sql
├── app/
│   ├── main.py                        # FastAPI + lifespan
│   ├── config.py                      # Pydantic settings
│   ├── database.py                    # Async SQLAlchemy
│   ├── models.py                      # ORM models
│   ├── core/
│   │   ├── task_loader.py             # Parse XML task files, validate schema
│   │   ├── scheduler.py               # APScheduler with PG persistence
│   │   ├── executor.py                # Multi-stage task execution engine
│   │   ├── context/
│   │   │   ├── __init__.py
│   │   │   ├── results_store.py       # Pull prior results from DB
│   │   │   ├── web_search.py          # Brave Search / SearXNG
│   │   │   ├── web_fetch.py           # Fetch and extract page content
│   │   │   ├── api_polygon.py         # Polygon.io price + fundamentals
│   │   │   ├── api_ebay.py            # eBay Browse API
│   │   │   └── cache.py               # TTL cache for shared context (macro brief)
│   │   ├── router.py                  # Per-stage provider selection
│   │   ├── judge.py                   # Judge LLM scoring from rubric in task XML
│   │   ├── evaluator.py               # Rubric-based scoring (fallback / Phase 1)
│   │   ├── alerts.py                  # Pushover, ntfy, Slack dispatchers
│   │   ├── children.py                # Child task spawning logic
│   │   └── evolution.py               # Prompt mutation + tournament (Phase 4)
│   ├── api/
│   │   ├── tasks.py                   # CRUD for tasks
│   │   ├── runs.py                    # Query run history, trigger runs
│   │   ├── feedback.py                # Thumbs up/down
│   │   └── system.py                  # Health, providers, stats
│   ├── dashboard/
│   │   ├── routes.py
│   │   └── templates/
│   └── tasks/                         # XML task definitions (version-controlled)
│       ├── stock_buy_opportunity.xml
│       ├── ebay_deal_hunter.xml
│       ├── earnings_sentiment.xml
│       └── tech_news_digest.xml
└── tests/
    ├── test_task_loader.py
    ├── test_executor.py
    ├── test_judge.py
    └── test_context_resolvers.py
```

---

## Database Schema

Use versioned task definitions, parent runs, item-level runs, stage results, judge scores, alerts, feedback, and ground-truth tracking. This avoids mixing a scheduled task run with the individual watchlist items it processes.

```sql
-- Stable task identity. One row per logical task.
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,                    -- e.g. stock_buy_opportunity
    domain          TEXT NOT NULL,                       -- trading | commerce | research
    status          TEXT NOT NULL DEFAULT 'active',
    current_version INT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Immutable XML snapshots. Evolution appends a new version; it never overwrites.
CREATE TABLE task_versions (
    task_id          TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    version          INT NOT NULL,
    parent_version   INT,
    task_xml         TEXT NOT NULL,
    parsed_metadata  JSONB NOT NULL DEFAULT '{}',
    parameters       JSONB NOT NULL DEFAULT '{}',
    prompt_hash      TEXT NOT NULL,
    created_by       TEXT NOT NULL DEFAULT 'manual',     -- manual | evolution
    created_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (task_id, version)
);

-- Parent run: one scheduler fire/manual trigger for a task version.
CREATE TABLE runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         TEXT NOT NULL,
    task_version    INT NOT NULL,
    trigger_type    TEXT NOT NULL,                       -- schedule | manual | child
    schedule_key    TEXT,                                -- e.g. cron_0930_open
    status          TEXT NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    total_cost_usd  NUMERIC(10,6) DEFAULT 0,
    error           TEXT,
    FOREIGN KEY (task_id, task_version) REFERENCES task_versions(task_id, version)
);

-- Work item run: one watchlist item/listing/ticker inside a parent run.
CREATE TABLE run_items (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    item_key        TEXT NOT NULL,                        -- ticker, listing_id, query, etc.
    params          JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'running',      -- running | skipped | succeeded | failed
    alert_sent      BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ
);
CREATE INDEX idx_run_items_run_id ON run_items(run_id);

-- Stage-level run results
CREATE TABLE run_stages (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_item_id   UUID NOT NULL REFERENCES run_items(id) ON DELETE CASCADE,
    stage_id      TEXT NOT NULL,                        -- e.g. "signal_scoring"
    stage_order   INT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    prompt_sent   TEXT,
    raw_output    TEXT,
    parsed_output JSONB,
    tokens_used   INT,
    cost_usd      NUMERIC(10,6),
    latency_ms    INT,
    skipped       BOOLEAN DEFAULT false,                -- if depends_on not met
    error         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_run_stages_run_item_id ON run_stages(run_item_id);

-- Judge scores per work item (separate from rubric evaluator)
CREATE TABLE judge_scores (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_item_id    UUID NOT NULL REFERENCES run_items(id) ON DELETE CASCADE,
    judge_model    TEXT NOT NULL,
    rubric_input   TEXT,                                -- what was sent to the judge
    raw_response   TEXT,
    criterion_scores JSONB,                             -- {"accuracy": 0.8, "completeness": 0.9}
    composite      NUMERIC(5,4),
    flags          JSONB DEFAULT '[]',
    recommendation TEXT,                                -- "alert" | "skip" | "watch"
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- User feedback powers alert_precision and evolution triggers.
CREATE TABLE feedback (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_item_id    UUID NOT NULL REFERENCES run_items(id) ON DELETE CASCADE,
    rating         TEXT NOT NULL,                        -- thumbs_up | thumbs_down | neutral
    note           TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);

-- Performance tracking (lagged ground truth)
CREATE TABLE performance_tracking (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_item_id      UUID NOT NULL REFERENCES run_items(id) ON DELETE CASCADE,
    task_id          TEXT NOT NULL,
    ticker           TEXT,
    alert_price      NUMERIC(10,4),
    target_price_30d NUMERIC(10,4),
    stop_loss_price  NUMERIC(10,4),
    alerted_at       TIMESTAMPTZ,
    price_10d        NUMERIC(10,4),                     -- filled in by performance_tracker child
    price_30d        NUMERIC(10,4),
    return_10d_pct   NUMERIC(8,4),
    return_vs_spy_10d NUMERIC(8,4),
    created_at       TIMESTAMPTZ DEFAULT now()
);

-- Alert dedup — prevents re-alerting same listing/ticker within window
CREATE TABLE alert_history (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id      TEXT NOT NULL,
    dedup_key    TEXT NOT NULL,                         -- e.g. ebay listing_id or ticker
    channel      TEXT NOT NULL,
    sent_at      TIMESTAMPTZ DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_alert_history_dedup ON alert_history(task_id, dedup_key, expires_at);

-- Provider budget/credit accounting for routing decisions.
CREATE TABLE provider_usage (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    task_id        TEXT,
    tokens_in      INT DEFAULT 0,
    tokens_out     INT DEFAULT 0,
    cost_usd       NUMERIC(10,6) DEFAULT 0,
    created_at     TIMESTAMPTZ DEFAULT now()
);
```

---

## Key Implementation Details

### 1. Task Loader (`core/task_loader.py`)

Parses XML task files into a typed `Task` dataclass at startup. Preserve the raw XML snapshot and a normalized parsed view. Validation should be strict enough that bad task files fail before the scheduler starts.

Validates:
- `success_criteria` weights sum to 1.0
- All `depends_on` stage IDs exist
- Provider priority lists are non-empty
- Required context inputs have valid sources
- Repeated elements are supported where the examples require them: multiple `<cron>`, multiple watchlist items, multiple stage routing blocks
- `execution/routing/stage[@ref]` references real prompt stages
- `depends_on`, child `condition`, schedule `skip_if`, and evolution `trigger_condition` parse into a safe expression AST
- Prompt placeholders refer to known task params, context inputs, stage outputs, or built-in runtime values
- Alert `format` placeholders resolve against final item context, judge score, run cost, and stage outputs
- `alerts/dedup_window_hours`, alert priority, digest timezone/content, and child `delay_hours` are parsed even when optional

Reloads from disk on `POST /api/tasks/{id}/reload`.

### 2. Multi-Stage, Fan-Out Executor (`core/executor.py`)

```python
async def execute_task(task: Task, params: dict) -> Run:
    run = await create_parent_run(task, params)
    work_items = expand_work_items(task.parameters, params)

    async for item in bounded_parallel(work_items, limit=task.schedule.max_concurrent):
        stage_outputs = {}
        item_context = await create_run_item(run, item)

        for stage in task.prompt.stages:
            # Check dependency gate. This only decides whether the next stage runs.
            if stage.depends_on and not evaluate_condition(stage.depends_on, stage_outputs):
                stage_outputs[stage.id] = StageResult(skipped=True)
                continue

            # Resolve context for this item and this stage
            context = await resolve_context(task.context_inputs, item, stage_outputs)

            # Render prompt
            prompt = render_prompt(stage, context)

            # Route to correct provider for THIS stage
            provider = await select_provider(task.execution.routing.for_stage(stage.id), session)

            # Call LLM with retry on parse failure
            result = await call_with_retry(provider, prompt, task.execution.retry)

            stage_outputs[stage.id] = result
            await store_stage_result(item_context, stage, result)

        # Judge composite output for this work item
        judge_score = await judge(task, item_context, stage_outputs)
        await store_judge_score(item_context, judge_score)

        # Dispatch alerts if task thresholds, filters, and dedup all pass
        if should_alert(task, item, stage_outputs, judge_score):
            await dispatch_alert(task, item_context, stage_outputs, judge_score)

        # Spawn children using the final item-scoped context
        await spawn_children(task, item_context, stage_outputs, judge_score)

    await finalize_parent_run(run)
    return run
```

`expand_work_items` is deliberately explicit:
- `stock_buy_opportunity`: one work item per `<parameters><watchlist><stock>`.
- `ebay_deal_hunter`: one work item per candidate listing after search and dedupe; preserve the parent watchlist item in params.
- Single-job tasks: one work item with the trigger params.

### 3. Judge LLM (`core/judge.py`)

- Sends the task's `<rubric>` text + all stage outputs to the judge model
- Judge model is always a cheap/fast model (claude-haiku, gemini-flash, llama)
- Returns criterion scores + composite weighted by `success_criteria` weights
- Never uses the same model as the executor (prevents grading own work)

### 4. Per-Stage Routing (`core/router.py`)

Stage routing is declared under `<execution><routing>`:
- Examples use `<stage ref="stage_id">` blocks with provider priority lists
- Single-stage/minimal tasks may use a flat provider priority list
- Falls back to the flat task-level provider priority if stage routing is not specified
- Ollama is always the final fallback regardless
- Per-stage cost tracked separately in `run_stages`
- Router checks provider health, configured API keys, monthly budget, free-tier quota, context length, and judge isolation before selection

### 5. Context Resolvers

| Source | Resolver | Notes |
|--------|----------|-------|
| `web_search` | `context/web_search.py` | Brave Search API; falls back to SearXNG |
| `web_fetch` | `context/web_fetch.py` | httpx fetch + readability extraction |
| `results_store` | `context/results_store.py` | Query prior runs from DB; supports filter + format |
| `api:polygon.io` | `context/api_polygon.py` | Price, fundamentals, transforms (RSI, MACD, etc.) |
| `api:ebay_browse` | `context/api_ebay.py` | Listings search, sold items, dedup against seen IDs |
| `api:unusual_whales` | *(Phase 4)* | Options flow |
| `cache` | `context/cache.py` | In-memory TTL cache; used for macro_context shared across tickers |

Resolver requirements:
- Return typed objects, not raw strings, so placeholders like `{market_price.median}` and `{listing.seller_feedback_pct}` fail early if missing.
- Record source freshness, fetch time, and fallback path in `run_items.params` or stage metadata.
- Enforce required vs optional inputs consistently: missing required context fails the work item; missing optional context injects a structured `null`/empty summary.
- Implement transforms as named functions with tests (`median_sold_price`, RSI, MACD, SMA distances, volume ratio), not prompt-side math.
- Add adapter capability tests before Phase 2/3 milestones, especially for eBay sold-price data and market-hours checks.

### 6. Alert Dispatcher (`core/alerts.py`)

- **Pushover** (primary — specified in both real tasks)
- **ntfy.sh** (secondary fallback)
- **Slack webhook** (optional)
- Dedup window: checks `alert_history` before sending — skips if same `dedup_key` within `dedup_window_hours`
- Digest mode: if no individual alert fires, send daily summary at configured time
- Alert gating combines task threshold, judge recommendation, task-specific filters, cooldowns, `max_alerts_per_day`, and dedup
- Dedup keys are task-specific: eBay uses listing ID; stock uses ticker plus alert window
- Alert formatting runs after all stages and judge scoring so placeholders can reference stage outputs, score, cost, model, and runtime values

### 7. Child Task Spawning (`core/children.py`)

```python
async def spawn_children(task, run, stage_outputs, judge_score):
    for child in task.children:
        if evaluate_condition(child.condition, stage_outputs, judge_score):
            child_params = extract_fields(child.pass_fields, stage_outputs)
            await scheduler.add_one_shot_job(
                task_id=child.task_id,
                params=child_params,
                delay_seconds=child.delay_hours * 3600,
            )
```

Child spawning runs item-by-item, not only at parent-run level. Child triggers supported by examples:
- `on_success`: item pipeline completed and condition passed.
- `on_alert_sent`: alert was actually dispatched, after dedup/cooldown checks.
- `delay_hours`: schedule immediately when omitted or `0`; otherwise enqueue a one-shot delayed run.

---

## Phased Implementation Checklist

### Phase 1 — Core Engine (Week 1-2)
Foundation: parse tasks strictly, run one work item through one or more stages, store item-scoped results.

- [ ] `init.sql` with full schema (`tasks`, `task_versions`, `runs`, `run_items`, `run_stages`, `judge_scores`, `feedback`, `alert_history`, `performance_tracking`, `provider_usage`)
- [ ] `task_loader.py` — XML parser, Task/Stage/Context/Execution/Alerts dataclasses
- [ ] XML validation for repeated crons, stage refs, provider lists, success weight sums, placeholders, optional alert/evolution fields
- [ ] Safe expression parser for `depends_on`, child conditions, schedule `skip_if`, and evolution trigger conditions
- [ ] `scheduler.py` — APScheduler with PG persistence, load tasks from `app/tasks/`
- [ ] `executor.py` — parent run + single work item + stage loop with stage gates
- [ ] `context/results_store.py` — prior results resolver
- [ ] `router.py` — per-stage provider selection, ollama fallback
- [ ] `evaluator.py` — rubric fallback (for tasks without judge rubric)
- [ ] `models.py` — all ORM models including run_stages, judge_scores
- [ ] API: task CRUD, manual run trigger, run history
- [ ] First task: `tech_news_digest.xml` (1 stage, web_search context, judge_llm scoring)

**Milestone**: `docker compose up` → a minimal task validates, runs on schedule, writes parent run/item/stage/judge records, and can be manually rerun

### Phase 2 — Multi-Stage + Judge LLM (Week 3-4)
Real tasks require this: eBay has 2 stages, stock has 3, and both depend on item fan-out.

- [ ] `executor.py` — watchlist/listing fan-out with bounded parallelism and per-item budgets
- [ ] `judge.py` — judge LLM scoring from task `<rubric>` XML
- [ ] `context/web_search.py` — Brave Search API integration
- [ ] `context/web_fetch.py` — page fetch + content extraction
- [ ] `context/cache.py` — TTL cache for shared inputs (macro context)
- [ ] `alerts.py` — Pushover dispatcher with dedup window
- [ ] Alert dedup via `alert_history` table
- [ ] `feedback.py` — thumbs up/down capture and feedback query API
- [ ] `tech_news_digest.xml` → local fixture version of `ebay_deal_hunter.xml` (2-stage, judge scoring, no live eBay dependency yet)
- [ ] Dashboard: job list, run history, stage breakdown, judge scores

**Milestone**: Multi-stage eBay fixture task runs every 3h, gates correctly, and sends/dedups a Pushover alert in a test channel

### Phase 3 — Trading Tasks + API Integrations (Week 5-6)

- [ ] `context/api_polygon.py` — price data + technical indicator transforms (RSI, MACD, SMA)
- [ ] `context/api_ebay.py` — eBay listing search plus a verified comparable-price source/adapter for sold-price median
- [ ] API capability smoke tests for Polygon, eBay OAuth, search, Pushover, and market calendar/status
- [ ] `children.py` — child task spawning with field passing
- [ ] `performance_tracking` table populated by `performance_tracker` child task
- [ ] `stock_buy_opportunity.xml` — 3-stage pipeline running 3×/day
- [ ] `earnings_sentiment.xml` — weekday morning sentiment pipeline
- [ ] Multiple crons per task (stock task has 3 cron entries)
- [ ] `market_hours_only` schedule gate (skip if market closed)
- [ ] Watchlist parameters: per-ticker config, cooldown, max alerts/day

**Milestone**: Stock scanner runs at market open/mid/close only on valid trading days; alerts include thesis + risk and create ground-truth tracking rows

### Phase 4 — Evolution + Ground Truth (Week 7+)

- [ ] `evolution.py` — prompt mutation targeting specific XML paths
- [ ] Versioned XML write path: new `task_versions` row, old version deprecated only after candidate wins
- [ ] Holdout set management (20% never used for training)
- [ ] DSPy integration for `dspy_prompt_optimization` strategy
- [ ] Lagged ground truth: `performance_tracker` fills in 10d/30d returns
- [ ] Feedback-aware metrics: thumbs-up rate, thumbs-down rate, alert suppression reasons
- [ ] Evolution triggers on `rolling_30d_composite_avg < 0.65` OR return underperformance
- [ ] Plateau detection: stop evolving after 3 cycles with no gain
- [ ] `context/api_unusual_whales.py` — options flow for catalyst signals

**Milestone**: Evolution proposes a new task version, evaluates it on non-holdout history, verifies it on holdout, and promotes only if it beats the current version by the configured margin

---

## External API Requirements

| API | Used by | Free tier | Key env var |
|-----|---------|-----------|-------------|
| Polygon.io | stock_buy_opportunity, earnings_sentiment | 5 calls/min | `POLYGON_API_KEY` |
| eBay Browse API | ebay_deal_hunter | Yes (OAuth) | `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` |
| Brave Search | tech_news_digest, stock task | 2000/month free | `BRAVE_SEARCH_API_KEY` |
| Pushover | all tasks (alerts) | $5 one-time | `PUSHOVER_USER_KEY`, `PUSHOVER_APP_TOKEN` |
| Unusual Whales | stock_buy_opportunity (Phase 4) | Paid | `UNUSUAL_WHALES_API_KEY` |

---

## Open Design Decisions

1. **XML storage**: Store immutable raw XML in `task_versions.task_xml` plus `parsed_metadata` and `parameters`. Reload from disk creates a new version if the XML hash changed.

2. **Multiple crons per task**: `stock_buy_opportunity` has 3 `<cron>` entries. APScheduler supports multiple triggers per job via separate job registrations with the same task ID + a suffix.

3. **Watchlist fan-out**: eBay and stock tasks iterate over `<watchlist>` items. Recommendation: one scheduler fire creates one parent `runs` row, then one `run_items` row per ticker/listing. Parallelize item execution with bounded concurrency from `<max_concurrent>`.

4. **Judge model isolation**: Judge should never be the same model as the executor. Enforce this in `judge.py` at runtime.

5. **Evolution mutation targets**: The schema supports targeting specific XML paths (e.g. `parameters/signal_weights`). Implement XPath-like targeting in Phase 4; before then, only manual edits create new task versions.

6. **Expression language**: Conditions appear in `depends_on`, child triggers, schedule skips, and evolution triggers. Use a tiny safe expression evaluator over parsed identifiers, comparisons, boolean operators, and literals. Do not use Python `eval`.

7. **Comparable price source for eBay**: The example requires sold-price median by same model and condition. Confirm the exact API/source before treating `median_sold_price` as production-ready.

8. **Market calendar**: `market_hours_only` and `early_close` require a market-calendar source. Add this adapter before enabling stock schedules in production.

9. **Budget semantics**: Example budgets are per ticker/per watchlist item. Track both per-item budget enforcement and parent-run total cost to avoid surprises.

10. **Alert formatter children vs built-in alerts**: The examples define both `<alerts>` and `alert_formatter` children. Decide whether `alert_formatter` is a real task for rich formatting, or whether built-in `alerts.py` handles formatting directly. Recommendation: start with built-in alerts; keep child support for performance tracking and later workflows.
