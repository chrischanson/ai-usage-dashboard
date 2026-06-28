# AI Usage Dashboard

Monitors token usage, session stats, and quota limits across AI coding assistants — AGY (Antigravity), OpenCode CLI, and Codex CLI (OpenAI) — in a single local dashboard.

## Quick Start

```bash
# Create venv and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (handles poller + server)
cd backend
PYTHONPATH=. python3 -m main

# Open http://127.0.0.1:8000
```

Or use the bundled script:

```bash
bash run.sh          # foreground
bash run.sh -b       # background (detached)
```

## Configuration

All settings via environment variables:

| Variable | Default | Description |
|---|---|---|
| `USAGE_DB_PATH` | `backend/usage.db` | SQLite database location |
| `USAGE_POLL_INTERVAL` | `600` | Poll interval in seconds |
| `USAGE_SUBPROCESS_TIMEOUT` | `20` | Timeout for CLI subprocess calls |
| `USAGE_NETWORK_TIMEOUT` | `10` | Timeout for network/quota calls |
| `USAGE_RETENTION_DAYS` | `90` | History pruning window |
| `USAGE_HOST` | `127.0.0.1` | Bind address |
| `USAGE_PORT` | `8000` | Bind port |
| `USAGE_LOG_LEVEL` | `INFO` | Logging level |

## Auto-start on Boot

**systemd** (Linux with systemd):
```bash
sudo bash install/install.sh /path/to/project [user]
sudo systemctl start usage-dashboard
```

**SysVinit** (containers, older Linux):
```bash
# install/init.d/usage-dashboard is pre-installed with update-rc.d
sudo /etc/init.d/usage-dashboard start
```

## Project Structure

```
backend/          FastAPI server, parsers, poller, DB layer
frontend/         Static HTML/CSS/JS dashboard (Chart.js)
install/          systemd service + SysVinit scripts
DESIGN.md         Architecture and design decisions
verify.py         Integration test suite (292 checks)
```

## Data Sources

- **AGY (Antigravity)**: Quota from Cloud Code API, usage from local conversation DBs
- **OpenCode**: Cost/tokens from `opencode stats --models`, usage from conversation DBs
- **Codex (OpenAI)**: Rate limits from websocket events, plan from session JWT

## License

MIT
