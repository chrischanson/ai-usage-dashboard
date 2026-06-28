# Agent Guidelines: Workspace Main

Welcome! This file provides the context, coding guidelines, and commands you need to work efficiently in this repository.

## Repository Overview

This repository contains multiple research and development projects:
- **`research/world_cup_2026/`**: LLM forecasting system for the 2026 World Cup. Uses `run_day.sh` as the main orchestrator.
- **`research/marathon_tracker/`**: Tools for tracking marathon deadlines, using LLM-based data extraction.
- **`public_projects/video-compressor/`**: Video compression utilities (built with Bazel).
- **`internal_projects/hello_world/`**: Bazel-based hello world.
- **`public_projects/ai-usage-dashboard/`**: Full-stack AI Usage Dashboard monitoring AGY usage/quota, OpenCode stats, and Codex CLI usage with per-source tab views.
- **`skills/`**: Structured agent skills library.

---

## Coding Standards & Conventions

### Python
- Use Python 3.12+ features.
- Avoid external non-standard library dependencies for simple utilities.
- Write robust unit tests using the standard library `unittest` framework.

### Bazel
- Use Bazel version 9.x.
- All target definitions go in `BUILD` or `BUILD.bazel`.
- Module dependencies are defined in `MODULE.bazel`.

### Shell Scripts
- Use `bash` (always include `#!/bin/bash` or `#!/usr/bin/env bash`).
- Prefer standard exit-on-error and clean traps for cleanups.
- Avoid global path assumptions; resolve script directories relative to the script location.

---

## Running Tests

Before submitting any code changes, verify your modifications by running all tests.

### Python Tests (Marathon Tracker)
To run Python tests, you must specify the search path via `PYTHONPATH`:
```bash
PYTHONPATH=research/marathon_tracker python3 -m unittest discover -s research/marathon_tracker/tests
```

### Bazel Tests (All Projects)
To execute all Bazel builds and tests in the repository:
```bash
bazel test //...
```

### AI Usage Dashboard Verifier
To run the dashboard verifier (290+ checks covering server, HTML, JS, CSS, APIs, UX, a11y, hardening):
```bash
PYTHONPATH=backend python3 verify.py
```

---

## AI Usage Dashboard — Requirements

### Design Document
The full design is documented in `public_projects/ai-usage-dashboard/DESIGN.md` (M1–M9 build order, architecture, data model, API spec, frontend architecture, UX states, a11y, security, testing strategy).

### Data Sources
- **AGY (Antigravity)**: Quota from Cloud Code API (`loadCodeAssist` response `paidTier.name`). Usage from local conversation DBs.
- **OpenCode**: Cost/tokens from `opencode stats --models` subprocess. Usage from `parser.py`.
- **Codex (OpenAI)**: Rate limits from `logs_2.sqlite` websocket events (`codex.rate_limits`). Plan type from JWT in `auth.json`. Billing API as optional cost source.

### API Endpoints
| Endpoint | Method | Returns |
|---|---|---|
| `/api/usage/latest` | GET | Combined usage for all sources |
| `/api/usage/{source}/latest` | GET | Per-source usage (agy/opencode/codex) |
| `/api/usage/{source}/history` | GET | Per-source history series |
| `/api/quota/latest` | GET | Combined quota with plan labels |
| `/api/quota/{source}/latest` | GET | Per-source quota |
| `/api/usage/latest?deltas=true` | GET | Model deltas for Rate mode |

### Frontend Layout
- **Header**: Title "Model Usage Dashboard" + time range buttons + Live pill in one row. No subtitle.
- **Tabs**: All (combined), AGY, OpenCode, Codex (OpenAI). Tab label is "All", not "Combined (All)".
- **Overview + Quota**: Side-by-side in `.stats-row` flex container.
- **Overview Cards**: 2×2 grid. Row 1: Sessions/Messages (same row, same size, separated by `/`) | Cache Reads. Row 2: Input Tokens | Output Tokens.
- **History Chart**: Stacked area (Total mode) or individual lines (Rate mode).
- **Model Distribution**: Donut chart. Title adapts to mode.
- **Mode Toggle**: Total/Rate. Affects history chart + model chart + overview cards.
- **Time Range**: 1h/6h/1d/1w/1m/3m/all. Affects entire page (overview + history chart). Relative to data's latest timestamp, not `Date.now()`.

### Quota Display
- **AGY**: Model groups with limit bars. Plan badge dynamic from API (`paidTier.name`).
- **OpenCode**: Total cost display.
- **Codex**: Monthly limit % bar + plan badge only. No cost display (unhelpful). Plan from JWT (`chatgpt_plan_type`).

### Security
- All user/API-sourced strings escaped via `escapeHtml()` before `innerHTML` injection.
- No secrets or keys logged or exposed.

### Server
- Start via: `cd backend && PYTHONPATH=. python3 -m main` (handles poller + server).
- Alternative: `bash run.sh` (creates venv, installs deps, starts).
- Auto-start: `sudo bash install/install.sh /path/to/project [user]` (systemd) or the pre-installed init.d script.
- Config env vars: `USAGE_HOST`, `USAGE_PORT`, `USAGE_DB_PATH`, etc. See README.
- Poll interval: 10 minutes (600s).

### Mobile Responsive
- Breakpoint at 640px: container padding, header stacking, scrollable tabs, single-column layouts, 24-hour time labels.

### UX States & A11y
- Loading: skeleton placeholders (`.skeleton` shimmer). Error: banner with retry/dismiss. Empty: friendly guidance text. Stale: amber indicator after 2min. Offline: red indicator, defers refresh.
- Tabs: `role="tablist"`, `role="tab"`, `aria-selected`, `role="tabpanel"`, ArrowLeft/ArrowRight keyboard nav.
- Focus: `:focus-visible` blue outline ring.
- Motion: `@media (prefers-reduced-motion)` disables all animations.
- Touch: all interactive elements `min-height: 44px`.
- Contrast: `--text-primary: #e8edff`, `--text-secondary: #8a9fc8` on `#0a0f1e` bg (AA 4.5:1+).

### Design (Build Order)
The dashboard follows a 9-milestone build order from `DESIGN.md`: M1 (Config+DB), M2 (Parser contract), M3 (Quota), M4 (Poller), M5 (API), M6 (Entry point), M7 (Frontend shell), M8 (UX+a11y), M9 (Hardening). Completed all 9 milestones.

---

## Agent Setup & MCP Configs

This workspace is optimized for agent session continuity:
- **CLI & IDE Sync:** `~/.gemini/antigravity-cli/brain` is symlinked to `~/.gemini/antigravity-ide/brain`.
- **MCP Servers:** A local filesystem MCP server is configured at `~/.gemini/config/mcp_config.json` and `~/.config/opencode/opencode.jsonc` to allow secure reads/writes inside `/home/dev/workspace/main`.
- **Structured Skills:** All workflow-specific instructions reside in [skills/superpowers](file:///home/dev/workspace/main/skills/superpowers/).
