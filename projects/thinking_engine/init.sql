-- Thinking Engine — Database Initialization
-- This file is auto-run by PostgreSQL on first container start
-- via /docker-entrypoint-initdb.d/

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- Job definitions
-- ============================================================
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    version         INT NOT NULL DEFAULT 1,
    schedule        TEXT,                          -- cron expression or NULL for manual-only
    enabled         BOOLEAN DEFAULT true,
    prompt_template TEXT NOT NULL,
    context_config  JSONB DEFAULT '[]'::jsonb,     -- list of context source definitions
    budget_max_tokens INT DEFAULT 2000,
    budget_max_cost   NUMERIC(10,6) DEFAULT 0.05,
    fitness_config    JSONB NOT NULL,               -- evaluator rules
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Run history
-- ============================================================
CREATE TABLE runs (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id        UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    job_version   INT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    prompt_sent   TEXT,
    raw_output    TEXT,
    parsed_output JSONB,
    score         NUMERIC(5,4),                    -- 0.0000 to 1.0000
    score_details JSONB,                           -- per-rule breakdown
    tokens_used   INT,
    cost_usd      NUMERIC(10,6),
    latency_ms    INT,
    error         TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_runs_job_id ON runs(job_id);
CREATE INDEX idx_runs_score ON runs(score);
CREATE INDEX idx_runs_created ON runs(created_at DESC);

-- ============================================================
-- Evolution history (prompt mutations)
-- ============================================================
CREATE TABLE evolutions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_version    INT NOT NULL,
    to_version      INT NOT NULL,
    old_prompt      TEXT,
    new_prompt      TEXT,
    old_avg_score   NUMERIC(5,4),
    new_avg_score   NUMERIC(5,4),
    variants_tested INT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Embeddings for semantic search over past outputs
-- ============================================================
CREATE TABLE run_embeddings (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id     UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    embedding  vector(768),                        -- nomic-embed-text = 768 dims
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Index created after enough data exists (ivfflat needs rows)
-- CREATE INDEX idx_run_embeddings ON run_embeddings
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- Provider credit balances
-- ============================================================
CREATE TABLE provider_credits (
    provider    TEXT PRIMARY KEY,
    balance_usd NUMERIC(10,4) DEFAULT 0,
    daily_limit NUMERIC(10,4),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Seed default providers
INSERT INTO provider_credits (provider, balance_usd, daily_limit) VALUES
    ('ollama',    999999.00, 999999.00),
    ('groq',     0.00, NULL),
    ('gemini',   0.00, NULL),
    ('openai',   0.00, NULL),
    ('anthropic', 0.00, NULL);

-- ============================================================
-- User feedback on outputs
-- ============================================================
CREATE TABLE feedback (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id     UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    useful     BOOLEAN NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================
-- Daily spend tracking
-- ============================================================
CREATE TABLE daily_spend (
    date        DATE PRIMARY KEY DEFAULT CURRENT_DATE,
    total_usd   NUMERIC(10,6) DEFAULT 0,
    run_count   INT DEFAULT 0
);
