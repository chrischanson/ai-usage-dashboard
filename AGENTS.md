# Agent Guidelines: Workspace Main

Welcome! This file provides the context, coding guidelines, and commands you need to work efficiently in this repository.

## Repository Overview

This repository contains multiple research and development projects:
- **`research/world_cup_2026/`**: LLM forecasting system for the 2026 World Cup. Uses `run_day.sh` as the main orchestrator.
- **`research/marathon_tracker/`**: Tools for tracking marathon deadlines, using LLM-based data extraction.
- **`public_projects/video-compressor/`**: Video compression utilities (built with Bazel).
- **`internal_projects/hello_world/`**: Bazel-based hello world.
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

---

## Agent Setup & MCP Configs

This workspace is optimized for agent session continuity:
- **CLI & IDE Sync:** `~/.gemini/antigravity-cli/brain` is symlinked to `~/.gemini/antigravity-ide/brain`.
- **MCP Servers:** A local filesystem MCP server is configured at `~/.gemini/config/mcp_config.json` and `~/.config/opencode/opencode.jsonc` to allow secure reads/writes inside `/home/dev/workspace/main`.
- **Structured Skills:** All workflow-specific instructions reside in [skills/superpowers](file:///home/dev/workspace/main/skills/superpowers/).
