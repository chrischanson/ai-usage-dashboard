# Thinking Engine — System Plan v1.0

## What It Is

A self-hosted, self-improving agentic pipeline that accepts jobs, runs them on a schedule, routes compute across multiple LLM providers based on credit availability, evaluates output quality, and uses that quality signal to iteratively rewrite its own prompts and job definitions over time.

---

## Goal Statement

**Desired Outcome**: A self-hosted, continuously improving research automation system that monitors multiple domains simultaneously — market signals, technical developments, professional intelligence, and personal interests — and proactively surfaces only the findings that cross a quality threshold worth your attention, delivered as concise alerts. The system runs unattended, costs near-zero in compute by intelligently routing across free and paid LLM credits, and gets measurably better at knowing what's worth alerting on over time through autonomous prompt evolution.

**What it replaces**: Hours of manual reading, tab-switching, and synthesis — replaced by a system that reads broadly, thinks deeply, and interrupts you rarely but valuably.

> A self-improving research engine that reads everything, learns what matters to you, and alerts you only when it finds something worth your time.

---

## Success Criteria (6-month)

1. **Alert precision ≥ 80%** — at least 8/10 alerts are genuinely useful (measured by thumbs up/down feedback)
2. **≥ 5 hours saved per week** — across domains, handles research you'd otherwise do manually
3. **Cost under $20/month** — routes to free tiers for high-frequency jobs, reserves paid credits for quality-critical jobs

---

## Core Concepts

### Job
A unit of work with:
- A **prompt template** (parameterized with context variables)
- A **schedule** (cron expression, or manual trigger)
- A **fitness function** (how to score the output)
- A **context pack** (data injected at runtime: prior results, web search, RSS, files)
- A **budget cap** (max tokens / max cost per run)

### Credit Router
Tracks remaining credits across providers. Routes each job to the cheapest capable model that fits within budget. Falls back to local Ollama (always free). Uses LiteLLM as the abstraction layer.

### Evaluator
Scores each output. Three modes:
1. **Rubric-based** — deterministic rules (e.g. "does the output contain a float in range?")
2. **LLM-as-judge** — a cheap model grades the expensive model's output
3. **Signal-based** — correlation of prediction with ground truth (for trading research)

### Self-Improvement Loop
Reads the results store, finds low-scoring runs, generates prompt variants via meta-prompting, reruns with the variants on a holdout evaluation set, keeps winners. Gradually surfaces better job definitions. Guards against overfitting with train/holdout splits.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Runtime | Python 3.12 | asyncio for concurrent job execution |
| Job scheduler | APScheduler | AsyncIOScheduler, persisted to PostgreSQL |
| LLM abstraction | LiteLLM | Unified API, 100+ providers |
| Results store | PostgreSQL 17 + pgvector | Structured data + semantic search over past runs |
| Embedding model | nomic-embed-text (local) | Via Ollama, 768 dimensions, no API cost |
| Job definitions | YAML + Pydantic | Version-controlled, human-editable, validated |
| API layer | FastAPI | REST endpoints + async job execution |
| Dashboard | Jinja2 + HTMX | Server-rendered, no JS build step |
| Local LLM | Ollama | Free fallback, always available |
| Hosting | Docker Compose on home server | 3 containers: db, engine, ollama |

---

## Directory Structure

```
thinking-engine/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── requirements.txt
├── init.sql                          # DB schema + pgvector extension
├── app/
│   ├── __init__.py
│   ├── main.py                       # FastAPI + lifespan (scheduler start/stop)
│   ├── config.py                     # Pydantic Settings from env
│   ├── database.py                   # async SQLAlchemy engine + session
│   ├── models.py                     # ORM models
│   ├── core/
│   │   ├── scheduler.py              # APScheduler setup, job registration
│   │   ├── router.py                 # Credit router — cheapest provider selection
│   │   ├── executor.py               # Full run pipeline: context → LLM → evaluate → store
│   │   ├── evaluator.py              # Fitness scoring (rubric, llm-judge, signal)
│   │   ├── context.py                # Context resolvers (web, prior_results, rss, file)
│   │   └── evolution.py              # Prompt mutation + tournament selection
│   ├── api/
│   │   ├── jobs.py                   # CRUD for jobs
│   │   ├── runs.py                   # Query/trigger runs
│   │   ├── feedback.py               # Thumbs up/down
│   │   └── system.py                 # Health, providers, stats
│   ├── dashboard/
│   │   ├── routes.py                 # Jinja2 HTML routes
│   │   ├── templates/                # base.html, index.html, job_detail.html, partials/
│   │   └── static/style.css
│   └── jobs/                         # YAML job definitions
│       └── news_digest.yaml
└── tests/
```

---

## Job YAML Schema

```yaml
id: earnings_sentiment_v1
description: Analyze last earnings call for a given ticker
schedule: "0 8 * * 1-5"   # weekdays 8am
budget:
  max_tokens: 2000
  max_cost_usd: 0.05
context:
  - type: web_search
    query: "{ticker} earnings call transcript Q{quarter} {year}"
  - type: prior_results
    job_id: earnings_sentiment
    last_n: 5
prompt_template: |
  You are a quantitative analyst. Given the following earnings call transcript:
  {transcript}
  
  Prior sentiment scores for context:
  {prior_results}
  
  Output a JSON object with:
  - sentiment_score: float -1.0 to 1.0
  - key_themes: list of strings
  - forward_guidance: string
  - confidence: float 0.0 to 1.0
fitness:
  type: rubric
  rules:
    - field: sentiment_score
      check: is_float_in_range(-1, 1)
    - field: key_themes
      check: is_list_min_length(2)
  bonus:
    - type: signal_correlation
      target: price_5d_return
```

---

## Self-Improvement Loop (Pseudocode)

```python
async def evolution_cycle(job_id: str, n_variants: int = 5):
    # Pull recent runs, split into train/holdout
    all_runs = store.get_runs(job_id, limit=50)
    train, holdout = split(all_runs, holdout_pct=0.2)
    
    bad_runs = [r for r in train if r.score < 0.6]
    good_runs = [r for r in train if r.score > 0.8]

    # Generate prompt variants via meta-prompt
    variants = mutate_prompts(
        base_prompt=job.prompt_template,
        bad_examples=bad_runs,
        good_examples=good_runs,
        n=n_variants
    )

    # Score each variant on holdout set (overfitting guard)
    scores = []
    for v in variants:
        holdout_scores = []
        for example in holdout:
            result = await router.run(v, context=example.context)
            score = evaluator.score(result, job.fitness)
            holdout_scores.append(score)
        scores.append((v, mean(holdout_scores)))

    # Keep best performer only if it beats current
    best_prompt, best_score = max(scores, key=lambda x: x[1])
    if best_score > job.current_avg_score:
        job.update_prompt(best_prompt)
        job.bump_version()
        store.log_evolution(job_id, best_prompt, best_score)
```

---

## Credit Router Logic

```python
PROVIDERS = [
    {"name": "groq",      "cost_per_1k": 0.00,  "models": ["llama-3.1-70b"]},
    {"name": "gemini",    "cost_per_1k": 0.002, "models": ["gemini-flash-2.0"]},
    {"name": "anthropic", "cost_per_1k": 0.003, "models": ["claude-haiku-4-5"]},
    {"name": "openai",    "cost_per_1k": 0.004, "models": ["gpt-4o-mini"]},
    {"name": "ollama",    "cost_per_1k": 0.000, "models": ["qwen3:8b"]},  # local fallback
]

def select_provider(job: Job, credits: dict) -> str:
    for p in sorted(PROVIDERS, key=lambda x: x["cost_per_1k"]):
        if credits.get(p["name"], 0) > job.budget.max_cost_usd:
            return p["name"]
    return "ollama"   # always available locally
```

---

## Phases

### Phase 1 — Foundation (Week 1-2)
- [ ] Docker Compose: PostgreSQL + FastAPI + Ollama
- [ ] Full DB schema (jobs, runs, evolutions, embeddings, credits, feedback)
- [ ] APScheduler with PostgreSQL persistence
- [ ] Executor pipeline (context → LLM → evaluate → store)
- [ ] Rubric evaluator
- [ ] REST API: jobs CRUD + manual run trigger + run history
- [ ] First job: news digest with rubric scoring

**Milestone**: `docker compose up` → create job via curl → trigger run → see scored output

### Phase 2 — Dashboard + Multi-Provider (Week 3-4)
- [ ] Jinja2 + HTMX dashboard (job list, run history, score charts)
- [ ] Multi-provider routing (Groq, Gemini, OpenAI, Anthropic)
- [ ] Credit tracking + daily spend limits
- [ ] Web search context resolver
- [ ] Thumbs up/down feedback system
- [ ] Stats page (spend, scores, alert precision)

**Milestone**: Browser dashboard with live job monitoring. Auto-routing to cheapest provider.

### Phase 3 — Evolution (Week 5-6)
- [ ] Prompt mutation via meta-prompting
- [ ] Tournament selection on train/holdout split
- [ ] Job versioning + evolution history
- [ ] Weekly evolution cron for eligible jobs
- [ ] Evolution timeline in dashboard

**Milestone**: Prompts auto-improve measurably. Evolution history visible.

### Phase 4 — Alerts + Trading Signal (Week 7+)
- [ ] Notifications (Slack / ntfy.sh / email) on high-score outputs
- [ ] Earnings sentiment job with SEC EDGAR data
- [ ] Signal-correlation evaluator
- [ ] Backtest harness (replay historical data, measure accuracy)
- [ ] Multi-agent chaining (job outputs feed into other jobs)

---

## Key Design Decisions

1. **Fitness function design** — Start with rubric (deterministic), move to signal-correlation only once ground truth data exists.
2. **Overfitting guard** — Always hold out 20% of eval data. Evolved prompts that game the metric on training data will fail on holdout.
3. **Evolution frequency** — Weekly default. Daily risks burning credits on low-signal mutations.
4. **Credit burn rate** — Hard stop: if daily spend > $X, pause all non-local jobs and fall through to Ollama.
5. **Job isolation** — Each job runs in its own async context. One failing job must not block others.

---

## Data Sources (Phase 4)

- SEC EDGAR API (free, earnings filings)
- Alpha Vantage or Polygon.io (price data for backtesting)
- Unusual Whales or Tradier (options flow)
- Brave Search API (web search for context)
- RSS feeds (news, blogs, research)
